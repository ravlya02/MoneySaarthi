# Spec: Web Search Agent

## Overview
Implements the Web-Search Agent (§C.1) so the AI orchestrator can retrieve live market
data — current top-performing mutual funds by category/horizon and prevailing fixed-income
rates (FD, RD, PPF, Sukanya, NPS, SCSS) — using Gemini's native function-calling loop
backed by the Tavily search API. The agent executes a pre-derived, planned shortlist of
searches (never free-explores), scrapes raw Tavily snippets down to typed `MarketFact`
JSON before results touch Gemini, enforces hard latency / cost bounds (max 3 tool calls,
8 s per-call timeout, 25 s global budget), and caches results in the existing
`market_data_cache` table keyed by `(tool, params, date)`. This unblocks the full Compute
phase of the report pipeline: the orchestrator can now pass live data into the Gemini
synthesis prompt rather than noting "market data unavailable".

## Depends on
- Step 01 — Auth / session (JWT-based `user_id`)
- Step 02 — Database schema (`market_data_cache` table already in `schema.sql`)
- Step 06 — Onboarding form (produces `EngineOutput` with current vs. target allocation
  gaps that drive the planned search list)

## Architecture phase
**Compute** — runs inside `generate_report()` background worker, between the deterministic
engine and Gemini synthesis (Phase 2 of §A.3).

## Routes
No new routes.

## Database changes
`market_data_cache` already exists in `app/db/schema.sql` with the correct schema and
index. No DDL changes required.

The table intentionally has no RLS (it stores only public market facts, no PII). The worker
writes via `service_role`; any authenticated read is fine. No `policies.sql` change needed.

## Pydantic models

**Modify:** `app/models/reports.py`
- Add `MarketFact` Pydantic model (promote from `@dataclass` in `web_search.py` to a
  proper Pydantic model so it can be serialised into the prompt and cached as JSON):

```python
class MarketFact(BaseModel):
    label: str          # e.g. "Mirae Asset Large Cap Fund – 5Y CAGR"
    value: str          # e.g. "18.4%"
    source_url: str
    fetched_at: str     # ISO-8601 date string
```

**No other model changes.**

## Templates
No template changes.

## Engine / AI changes

### `app/ai/web_search.py` — full implementation (replaces all `NotImplementedError` stubs)

**Constants (update existing):**
```python
MAX_TOOL_CALLS   = 3   # hard cap per report
PER_CALL_TIMEOUT = 8   # seconds — per Tavily call
GLOBAL_BUDGET    = 25  # seconds — wall-clock budget for the whole agent run
```

**Tool declarations (TOOLS list — keep as-is):** already correct, no changes.

**New internal helpers:**

1. `_cache_get(tool: str, params: dict) -> list[MarketFact] | None`
   - Queries `market_data_cache` via `service_client()` where
     `tool = tool AND params = params AND cache_date = current_date`.
   - Returns deserialised `MarketFact` list if found, `None` on miss.

2. `_cache_set(tool: str, params: dict, facts: list[MarketFact], source_urls: list[str]) -> None`
   - Upserts a row into `market_data_cache` via `service_client()`.
   - `result` column stores `[f.model_dump() for f in facts]` as JSONB.
   - Uses the `unique (tool, params, cache_date)` constraint (upsert on conflict).

3. `_call_tavily(query: str, include_domains: list[str], timeout: float) -> list[dict]`
   - Calls `TavilyClient(api_key=settings.web_search_api_key).search(...)` with
     `max_results=5`, `include_domains=include_domains`, wrapped in `asyncio.wait_for`
     with `timeout=PER_CALL_TIMEOUT`.
   - Preferred domains: `amfiindia.com`, `rbi.org.in`, `npscra.nsdl.co.in`,
     `nsiindia.gov.in`, `moneycontrol.com`, `valueresearchonline.com`.
   - Returns raw result dicts `{url, title, content, score}` or `[]` on timeout/error.

4. `_scrape_fund_facts(results: list[dict], category: str) -> list[MarketFact]`
   - Parses each result's `content` snippet for patterns like `"3Y: 18.4%"`, `"5Y CAGR:
     21.2%"`, `"ER: 0.52%"`, `"AUM: ₹12,345 Cr"` using compiled regex.
   - Returns one `MarketFact` per matched metric (label includes fund name + metric name).
   - Skips results with score < 0.5.

5. `_scrape_rate_facts(results: list[dict], instrument: str) -> list[MarketFact]`
   - Parses content for rate patterns like `"PPF: 7.1%"`, `"SCSS: 8.2%"`,
     `"FD rate: 7.0%"`.
   - Returns one `MarketFact` per rate found.

**Implement public functions:**

`search_top_funds(category, horizon_years, risk) -> list[MarketFact]`
1. Check cache via `_cache_get("search_top_funds", {"category": category, ...})`.
   Return cached result immediately on hit.
2. Build Tavily query:
   `f"top performing {category} mutual funds India 2025 {horizon_years}Y CAGR expense ratio"`
3. Call `_call_tavily(query, include_domains=[...], timeout=PER_CALL_TIMEOUT)`.
4. Scrape via `_scrape_fund_facts(results, category)`.
5. Cache via `_cache_set(...)`.
6. Return facts (empty list if nothing scraped — caller handles partial data).

`get_fixed_income_rates(instrument) -> list[MarketFact]`
1. Check cache.
2. Build query: `f"current {instrument} interest rate India 2025 RBI"`
3. Call Tavily, scrape via `_scrape_rate_facts`, cache, return.

`gather_market_data(planned_searches: list[dict]) -> list[MarketFact]`
- Async. Tracks `calls_made` and `elapsed` against hard bounds.
- For each planned search `{"tool": ..., "params": {...}}`:
  - Bail if `calls_made >= MAX_TOOL_CALLS` or `elapsed >= GLOBAL_BUDGET`.
  - Dispatch to `search_top_funds` or `get_fixed_income_rates` accordingly.
  - On per-call timeout or any exception: append nothing, log warning, continue.
- Returns accumulated `list[MarketFact]` (may be partial).
- If budget was exhausted before all searches, the returned list will be shorter;
  the orchestrator will note "live market data partially unavailable" in the prompt.

### `app/ai/orchestrator.py` — derive planned searches from engine gaps

Update `enrich_and_synthesize` to replace the empty `planned = []` stub:

```python
def _derive_planned_searches(engine: EngineOutput) -> list[dict]:
    """Map allocation gaps and goal horizons to a shortlist of tool calls."""
    searches = []
    cur = engine.current_allocation
    tgt = engine.target_allocation

    # Equity gap → find top fund for the underweight category
    equity_gap = tgt.equity - cur.equity
    if equity_gap > 5:
        searches.append({"tool": "search_top_funds",
                         "params": {"category": "LargeCap", "horizon_years": 5}})

    # Debt gap → fixed income rates
    debt_gap = tgt.debt - cur.debt
    if debt_gap > 5:
        searches.append({"tool": "get_fixed_income_rates",
                         "params": {"instrument": "FD"}})
        searches.append({"tool": "get_fixed_income_rates",
                         "params": {"instrument": "PPF"}})

    return searches[:MAX_TOOL_CALLS]  # respect hard cap at derivation time too
```

Replace `planned: list[dict] = []` with `planned = _derive_planned_searches(engine)`.
Import `MAX_TOOL_CALLS` from `app.ai.web_search`.

## Files to change
- `app/ai/web_search.py` — full implementation (replaces all stubs)
- `app/ai/orchestrator.py` — replace `planned = []` stub with `_derive_planned_searches`
- `app/models/reports.py` — add `MarketFact` Pydantic model; remove `@dataclass` from `web_search.py`
- `requirements.txt` — add `tavily-python`

## Files to create
- `tests/test_web_search.py` — unit + integration tests (see Definition of Done)

## New dependencies
```
tavily-python>=0.3
```
Add to `requirements.txt`.

## Rules for implementation
- Use `Decimal` for all money math — never float (no money math in this module, but if
  any monetary scraped value needs comparison use `Decimal`).
- Tax rules must live in `app/engine/tax/rules.py`, keyed by assessment year — this module
  does not touch tax rules.
- Gemini writes narrative only; it must never compute or invent a rupee figure — the web
  search agent provides live market data but no user financial calculations.
- After Gemini responds, run the numeric-consistency check in `app/ai/validation.py` —
  this module feeds facts *to* the prompt; the check still runs downstream in the
  orchestrator after Gemini synthesis.
- RLS is enforced on every user table; `market_data_cache` intentionally has no RLS
  (public data only, no PII). Never store any `user_id` or household data in this table.
- `service_role` key is used only for cache writes in the background worker — never in
  templates or client-facing code.
- All templates extend `app/templates/base.html` — this module has no templates.
- Scraping logic must use compiled regex (`re.compile` at module level), not raw string
  parsing, so patterns are auditable and testable in isolation.
- Every `MarketFact` must carry `source_url` and `fetched_at` so the dashboard can cite
  them. Never fabricate a source URL.
- Hard bounds are not advisory — they must be enforced with `asyncio.wait_for` and a
  monotonic clock (`time.monotonic()`), not just counted optimistically.
- On any exception inside a single tool call (timeout, network error, parse failure),
  log a warning and continue; do not let one failed search abort the whole agent run.
- The `_derive_planned_searches` function must cap its output at `MAX_TOOL_CALLS` so the
  orchestrator can never accidentally schedule more calls than the budget allows.

## Definition of done
- [ ] `pytest tests/test_web_search.py` passes all tests without a live Tavily key
  (cache-hit path and scraping logic are tested with mocked Tavily responses).
- [ ] `_cache_get` returns a cached result on second call without invoking Tavily (verified
  by asserting Tavily is called exactly once across two identical `search_top_funds` calls
  in the test suite).
- [ ] `gather_market_data` with a plan of 5 items respects `MAX_TOOL_CALLS=3` and returns
  at most 3 batches of facts (tested with mock).
- [ ] `gather_market_data` respects the global 25 s budget: when mock tool calls each
  take 10 s, the third call is skipped and the function returns in ≤ 25 s with 2 batches.
- [ ] `_scrape_fund_facts` extracts at least one `MarketFact` from the fixture snippets
  in `tests/test_web_search.py` that contain realistic Tavily-style content strings.
- [ ] `_scrape_rate_facts` extracts PPF and SCSS rates from a fixture snippet.
- [ ] `_derive_planned_searches(engine)` returns `{"tool": "search_top_funds", ...}` when
  `tgt.equity - cur.equity > 5` and `{"tool": "get_fixed_income_rates", ...}` when
  `tgt.debt - cur.debt > 5`.
- [ ] `MarketFact` is importable from `app.models.reports` and fully Pydantic-serialisable
  (`.model_dump()` and `.model_json_schema()` work without error).
- [ ] `app/ai/web_search.py` imports without error when `WEB_SEARCH_API_KEY` is empty
  (the key is only read at call time, not at import time).
- [ ] `pytest tests/` still shows all 33 existing tests green after the changes.

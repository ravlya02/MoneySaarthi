"""Web-Search Agent (§C.1). Gemini function-calling loop, bounded by hard
limits. Results are scraped to structured facts before reaching Gemini."""

import asyncio
import json
import logging
import re
import time
from datetime import date

from app.config import get_settings
from app.db.supabase_client import service_client
from app.models.reports import MarketFact

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS   = 3   # hard cap per report
PER_CALL_TIMEOUT = 8   # seconds, per Tavily call
GLOBAL_BUDGET    = 25  # seconds, wall-clock total for the whole agent run

# Compiled regex patterns — module-level so they are auditable and fast.
_CAGR_RE = re.compile(r'(\d+Y)\s*(?:CAGR)?[:\s]+(\d+\.?\d*)\s*%', re.IGNORECASE)
_ER_RE   = re.compile(r'(?:ER|expense\s+ratio)[:\s]+(\d+\.?\d*)\s*%', re.IGNORECASE)
_AUM_RE  = re.compile(r'AUM[:\s]+[₹Rs.]*\s*([\d,]+)\s*(?:Cr|crore)', re.IGNORECASE)
_RATE_RE = re.compile(r'([\w][\w\s/]*?)\s*(?:rate)?[:\s]+(\d+\.?\d*)\s*%', re.IGNORECASE)

# Trusted domains preferred by Tavily search — authoritative Indian financial sources.
_TRUSTED_DOMAINS = [
    "amfiindia.com",
    "rbi.org.in",
    "npscra.nsdl.co.in",
    "nsiindia.gov.in",
    "moneycontrol.com",
    "valueresearchonline.com",
]

# Tool declarations exposed to Gemini (function declarations).
TOOLS = [
    {
        "name": "search_top_funds",
        "description": "Find current top-performing mutual funds for a category/horizon.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["LargeCap", "MidCap", "SmallCap", "FlexiCap", "Index", "ELSS", "Debt", "Hybrid"],
                },
                "horizon_years": {"type": "integer"},
                "risk": {"type": "string", "enum": ["Conservative", "Moderate", "Aggressive"]},
            },
            "required": ["category"],
        },
    },
    {
        "name": "get_fixed_income_rates",
        "description": "Current FD / RD / PPF / Sukanya / NPS / SCSS rates.",
        "parameters": {
            "type": "object",
            "properties": {"instrument": {"type": "string"}},
            "required": ["instrument"],
        },
    },
]


# ---------------------------------------------------------------------------
# Cache helpers (market_data_cache table — no RLS, public facts only)
# ---------------------------------------------------------------------------

def _cache_get(tool: str, params: dict) -> list[MarketFact] | None:
    """Return cached MarketFact list for today, or None on miss."""
    try:
        db = service_client()
        resp = (
            db.table("market_data_cache")
            .select("result")
            .eq("tool", tool)
            .eq("params", json.dumps(params, sort_keys=True))
            .eq("cache_date", date.today().isoformat())
            .limit(1)
            .execute()
        )
        if resp.data:
            return [MarketFact(**r) for r in resp.data[0]["result"]]
    except Exception as exc:
        logger.warning("web_search: cache_get failed: %s", exc)
    return None


def _cache_set(tool: str, params: dict, facts: list[MarketFact], source_urls: list[str]) -> None:
    """Upsert scraped facts into market_data_cache. Best-effort — swallows errors."""
    try:
        db = service_client()
        db.table("market_data_cache").upsert(
            {
                "tool": tool,
                "params": json.dumps(params, sort_keys=True),
                "cache_date": date.today().isoformat(),
                "result": [f.model_dump() for f in facts],
                "source_urls": source_urls,
                "fetched_at": date.today().isoformat(),
            },
            on_conflict="tool,params,cache_date",
        ).execute()
    except Exception as exc:
        logger.warning("web_search: cache_set failed: %s", exc)


# ---------------------------------------------------------------------------
# Tavily call (sync — run via asyncio.to_thread in gather_market_data)
# ---------------------------------------------------------------------------

def _call_tavily(query: str, include_domains: list[str]) -> list[dict]:
    """Call Tavily and return raw result dicts. Returns [] on any failure."""
    try:
        from tavily import TavilyClient  # imported here so missing key doesn't break import
        client = TavilyClient(api_key=get_settings().web_search_api_key)
        response = client.search(query=query, max_results=5, include_domains=include_domains)
        return response.get("results", [])
    except Exception as exc:
        logger.warning("web_search: tavily call failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Scrapers — extract typed MarketFact objects from raw Tavily snippets
# ---------------------------------------------------------------------------

def _fund_name_from_title(title: str) -> str:
    """Best-effort fund name extraction from a page title."""
    name = title.split(" - ")[0].strip()
    return name or title[:60]


def _scrape_fund_facts(results: list[dict], category: str) -> list[MarketFact]:
    """Parse Tavily snippets into MarketFact objects for mutual funds."""
    facts: list[MarketFact] = []
    today = date.today().isoformat()

    for r in results:
        if r.get("score", 0) < 0.5:
            continue
        fund_name = _fund_name_from_title(r.get("title", ""))
        content = r.get("content", "")
        url = r.get("url", "")

        for m in _CAGR_RE.finditer(content):
            facts.append(MarketFact(
                label=f"{fund_name} – {m.group(1)} CAGR",
                value=f"{m.group(2)}%",
                source_url=url,
                fetched_at=today,
            ))

        for m in _ER_RE.finditer(content):
            facts.append(MarketFact(
                label=f"{fund_name} – Expense Ratio",
                value=f"{m.group(1)}%",
                source_url=url,
                fetched_at=today,
            ))

        for m in _AUM_RE.finditer(content):
            facts.append(MarketFact(
                label=f"{fund_name} – AUM",
                value=f"₹{m.group(1)} Cr",
                source_url=url,
                fetched_at=today,
            ))

    return facts


def _scrape_rate_facts(results: list[dict], instrument: str) -> list[MarketFact]:
    """Parse Tavily snippets into MarketFact objects for fixed-income rates."""
    facts: list[MarketFact] = []
    today = date.today().isoformat()
    instrument_lower = instrument.lower()

    for r in results:
        if r.get("score", 0) < 0.5:
            continue
        content = r.get("content", "")
        url = r.get("url", "")

        for m in _RATE_RE.finditer(content):
            label_candidate = m.group(1).strip()
            if instrument_lower in label_candidate.lower():
                facts.append(MarketFact(
                    label=f"{label_candidate} rate",
                    value=f"{m.group(2)}%",
                    source_url=url,
                    fetched_at=today,
                ))

    return facts


# ---------------------------------------------------------------------------
# Public tool functions (sync — dispatched via asyncio.to_thread)
# ---------------------------------------------------------------------------

def search_top_funds(
    category: str,
    horizon_years: int | None = None,
    risk: str | None = None,
) -> list[MarketFact]:
    """Find current top-performing mutual funds. Checks cache first."""
    params: dict = {"category": category, "horizon_years": horizon_years, "risk": risk}

    cached = _cache_get("search_top_funds", params)
    if cached is not None:
        return cached

    horizon = horizon_years or 5
    query = f"top performing {category} mutual funds India 2025 {horizon}Y CAGR expense ratio AUM"
    results = _call_tavily(query, _TRUSTED_DOMAINS)
    facts = _scrape_fund_facts(results, category)
    source_urls = [r.get("url", "") for r in results]

    _cache_set("search_top_funds", params, facts, source_urls)
    return facts


def get_fixed_income_rates(instrument: str) -> list[MarketFact]:
    """Fetch current FD / RD / PPF / Sukanya / NPS / SCSS rates. Checks cache first."""
    params: dict = {"instrument": instrument}

    cached = _cache_get("get_fixed_income_rates", params)
    if cached is not None:
        return cached

    query = f"current {instrument} interest rate India 2025 RBI official"
    results = _call_tavily(query, _TRUSTED_DOMAINS)
    facts = _scrape_rate_facts(results, instrument)
    source_urls = [r.get("url", "") for r in results]

    _cache_set("get_fixed_income_rates", params, facts, source_urls)
    return facts


# ---------------------------------------------------------------------------
# Orchestrator entry point
# ---------------------------------------------------------------------------

async def gather_market_data(planned_searches: list[dict]) -> list[MarketFact]:
    """Execute a pre-derived shortlist of searches within the global budget.
    On budget exhaustion, returns whatever was gathered — report notes partial data."""
    all_facts: list[MarketFact] = []
    calls_made = 0
    start = time.monotonic()

    for search in planned_searches:
        if calls_made >= MAX_TOOL_CALLS:
            logger.info("web_search: hit MAX_TOOL_CALLS=%d, stopping", MAX_TOOL_CALLS)
            break

        elapsed = time.monotonic() - start
        if elapsed >= GLOBAL_BUDGET:
            logger.warning("web_search: global budget %.1fs exhausted after %d calls", GLOBAL_BUDGET, calls_made)
            break

        tool = search["tool"]
        params = search.get("params", {})
        remaining = GLOBAL_BUDGET - (time.monotonic() - start)
        timeout = min(PER_CALL_TIMEOUT, remaining)

        try:
            if tool == "search_top_funds":
                facts = await asyncio.wait_for(
                    asyncio.to_thread(search_top_funds, **params),
                    timeout=timeout,
                )
            elif tool == "get_fixed_income_rates":
                facts = await asyncio.wait_for(
                    asyncio.to_thread(get_fixed_income_rates, **params),
                    timeout=timeout,
                )
            else:
                logger.warning("web_search: unknown tool %r — skipping", tool)
                facts = []

            all_facts.extend(facts)
            calls_made += 1

        except asyncio.TimeoutError:
            logger.warning("web_search: tool %s timed out after %.1fs", tool, timeout)
        except Exception as exc:
            logger.warning("web_search: tool %s raised %s", tool, exc)

    return all_facts

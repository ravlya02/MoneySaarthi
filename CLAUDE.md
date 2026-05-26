# CLAUDE.md

## Project overview
AI-driven personal finance, tax & investment advisory platform for India (FY 2025-26 / AY 2026-27;
Income Tax Act 2025 effective 1 Apr 2026). A FastAPI monolith with server-side rendering that captures
a household's financial intake, computes tax and asset-allocation figures deterministically, and uses
Gemini to write advisory narrative around those figures.

**Stack:** FastAPI + Jinja2 (SSR) · Supabase (PostgreSQL / Auth / RLS) · Gemini API · Qdrant Cloud
(RAG) · Plotly. Background worker handles report generation (FastAPI `BackgroundTasks` for MVP).

The authoritative design is **`documents/architecture.md`** — read it before implementing anything;
section references below (§A–§E) point into it.

## Critical guardrails (do not break these)
- **The LLM advises, it never computes money.** Every rupee, tax number, and allocation percentage is
  produced by deterministic Python *before* Gemini is called. Gemini only synthesizes narrative,
  rationale, and action items around pre-computed numbers. It must never recalculate or invent a figure.
  This is the single most important rule in the system. (§E.2, §C.3)
- **Tax rules live in a versioned, unit-tested rules module keyed by assessment year** — never in a
  prompt. New-year changes should be a data change, not a code rewrite. (§E.2)
- **Use `Decimal` for all money math, never float.** (§E.2)
- **After Gemini responds, run a numeric-consistency check:** scan the narrative for rupee figures and
  assert they match the engine's verified facts; reject/strip any number Gemini introduced. (§E.2)
- **RLS is enabled on every table.** A user can only touch rows where `user_id = auth.uid()`. Always
  derive `user_id` from the verified Supabase JWT, never from the request body; use `with check` on
  writes. (§B.3)
- **Two keys, two trust levels.** Browser/Jinja layer uses only the **anon key** (RLS enforced). The
  background worker uses the **`service_role` key** (bypasses RLS) and is the only writer of
  `tax_reports` / `investment_plans`. The `service_role` key stays in server-side env vars only —
  never in a template or client bundle. (§B.3)

## Architecture at a glance (§A)
Report generation is **asynchronous**, tracked via the `report_jobs` table. Three phases:
1. **Capture (sync, <500ms):** multi-step form POSTs; Pydantic validates every figure; validated payload
   written to `financial_inputs` (versioned JSONB snapshot); a `report_jobs` row is queued; redirect to
   dashboard in "generating" state.
2. **Compute (background, 10–90s):** worker runs the **deterministic engine first** (tax both regimes,
   target allocation, goal funding), then the AI orchestrator enriches (web search + RAG), assembles one
   prompt, gets narrative from Gemini, writes `tax_reports` / `investment_plans`, flips job to `complete`.
3. **Render (sync, <800ms):** dashboard polls/SSE; once complete, figures built server-side and rendered.

Deterministic numbers are always available even if the AI call fails — degrade to "report pending /
partial", never a 500 on submit.

## Data model (§B)
`auth.users` → `profiles` (1:1) and → `financial_inputs` (1:many, versioned). Each input version fans
out to `income_sources`, `expenses`, `liabilities`, `holdings`, `insurance_policies`, `goals`
(1:many, all `on delete cascade`). The engine consumes one input version and writes one
`investment_plans` and one `tax_reports` row, linked by `input_version`. Reports are immutable per
version. Index `user_id` on every table. Full DDL is in §B.2.

## AI subsystem (§C)
Three cooperating parts feeding one assembled prompt:
- **Web-Search Agent** — current market facts (top funds, FD/RD/PPF/Sukanya/NPS/SCSS rates) via Gemini
  function-calling. Bounded: max N tool calls, per-call + global timeouts, results scraped to structured
  JSON before reaching Gemini, cached by `(tool, params, date)`. (§C.1)
- **RAG / Qdrant** — authoritative for *rules only*: tax law and portfolio strategy. Two corpora
  (`tax_law_kb`, `portfolio_strategy_kb`). Tax passages filtered by `effective_ay` so AY 2026-27 never
  retrieves stale slabs. Gemini embeddings for index + query; semantic chunking; retrieve top-k then
  rerank to 4–6. (§C.2)
- **Gemini synthesis** — single sectioned prompt with provenance: `[VERIFIED FACTS]` (engine, immutable)
  / `[LIVE MARKET DATA]` (cite sources) / `[KNOWLEDGE BASE]` (rules) / `[OUTPUT FORMAT]` (strict JSON).
  Output is validated against schema. (§C.3)

## Frontend (§D)
- **Plotly:** build the figure server-side, serialize with `pio.to_json`, hydrate client-side with
  `Plotly.newPlot`. Do NOT use iframes or static images. Load Plotly once from CDN in the base template.
  Cache serialized figure JSON in `investment_plans.plan_detail`. (§D.1)
- **Form:** multi-step SSR mirroring the intake sections (Demographics → Income → Expenses → Loans →
  Savings/Investments → Insurance → Goals → Risk). Persist partial state server-side on each step
  transition so a refresh never loses a half-entered sheet. No SPA. (§D.2)

## Repo layout
- `documents/architecture.md` — authoritative reference design (read first).
- `documents/tax_document.pdf`, `documents/Investment_analysis_and_portfolio_management.pdf` — domain
  references for tax rules and investment management.

## Status
Greenfield — no application code scaffolded yet. Build/test/lint commands to be added here once tooling
lands.

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

## Auth architecture (server-side only)
All authentication is **fully server-side** — no Supabase JS SDK in any template.

- **`POST /register`** — admin API (`service_role` key) calls `admin.create_user({email_confirm: True})`.
  Email verification is disabled; accounts are immediately active. Never passes credentials to the browser.
- **`POST /auth/login`** — uses `anon_client()` to sign in with password server-side and sets an
  HttpOnly `access_token` cookie. No per-request client; no auto-heal logic.
- **`optional_user()`** — returns `CurrentUser | None`, never raises. Used on SSR pages to redirect
  unauthenticated users without triggering a 401 JSON response.
- **`current_user()`** — raises `HTTPException(401)`. Used only on JSON API endpoints (e.g. job status).
- **`?next=` deep-link** — `_safe_next()` validates the param (must start with `/`, must not start
  with `//`) before using it; prevents open-redirect attacks.
- **`authenticated=True`** — must be passed explicitly in every protected `TemplateResponse` context.
  `base.html` guards the nav bar with `{% if authenticated %}`.
- **Anon key / service_role key** — neither key is ever injected into template HTML or client JS.

## Repo layout
```
app/
  config.py              — pydantic-settings (env vars, assessment_year, debug flag)
  main.py                — FastAPI app; mounts /static; includes all routers
  dependencies.py        — current_user() raises 401; optional_user() returns None
  db/
    supabase_client.py   — anon_client() + service_client() (lru_cache singletons)
    schema.sql           — full DDL (all 12 tables + indexes + RLS enable)
    policies.sql         — RLS SELECT/INSERT/UPDATE policies per table
    triggers.sql         — updated_at trigger on profiles & report_jobs
    apply.py             — SQL-aware migration runner (loads .env, parses $$ blocks)
  models/
    auth.py              — SessionPayload, RegisterPayload, LoginPayload
    intake.py            — Pydantic intake models: HouseholdMember, IncomeSource,
                           Expense, Liability, Holding, InsurancePolicy, Goal,
                           IntakeSubmission. All money fields are Decimal.
    reports.py           — TaxResult, Allocation, GoalFunding, EngineOutput,
                           AINarrative (output models)
  engine/
    tax/rules.py         — RULES_BY_AY dict (AY 2026-27 new-regime slabs + 87A rebate)
    tax/compute.py       — compute_new_regime(), compute_tax() (old regime → stub)
    allocation.py        — current_allocation(), target_allocation() by risk profile
    goals.py             — evaluate_goal() (placeholder logic)
    runner.py            — run_engine() top-level entry point
  ai/
    web_search.py        — gather_market_data() (Gemini function-calling, bounded)
    rag.py               — retrieve_tax_passages(), retrieve_strategy_passages()
    gemini.py            — synthesize() — calls Gemini, returns AINarrative
    prompts.py           — build_prompt() — assembles [VERIFIED FACTS] + sections
    validation.py        — assert_no_hallucinated_numbers()
    orchestrator.py      — enrich_and_synthesize() — coordinates all AI parts
  worker/jobs.py         — generate_report() background task (engine → AI → DB)
  charts/figures.py      — Plotly figure builders (scaffold)
  routers/
    auth.py              — GET /login, GET /register, POST /register, POST /auth/login,
                           POST /auth/session, POST /auth/logout, GET /
    onboarding.py        — GET /onboarding/{step} (optional_user redirect),
                           POST /onboarding/submit (current_user)
    dashboard.py         — GET /dashboard (optional_user redirect),
                           GET /jobs/{job_id}/status (current_user, JSON 401)
    health.py            — GET /health
    templates.py         — Jinja2Templates singleton
  templates/
    base.html            — CDN Plotly, nav ({% if authenticated %}), block content
    login.html           — server-side only; fetch("/auth/login"); logged_out banner
    register.html        — server-side only; fetch("/register") + fetch("/auth/login")
    dashboard.html       — report view (Plotly hydration wired up TODO)
    dashboard_pending.html — polling / "generating" state
    onboarding/
      demographics.html  — placeholder form skeleton
documents/
  architecture.md        — authoritative reference design (read first)
  tax_document.pdf       — Income Tax Act 2025 reference
  Advisor_Knowledge_Base.docx — portfolio domain reference
tests/
  test_tax.py            — 2 unit tests: sub-rebate → 0 tax; high income → tax > 0
  test_auth.py           — session cookie, logout, login page render, root redirect
  test_registration.py   — 10 tests: GET /register render + security; POST /register
                           admin API call, error handling, Pydantic validation
  test_login_logout.py   — 10 tests: redirect-if-no-cookie, redirect-if-authed,
                           ?next= deep link, open-redirect rejection, 401 on API endpoint
requirements.txt         — fastapi, uvicorn, jinja2, pydantic[email]>=2,
                           pydantic-settings, supabase, httpx, google-generativeai,
                           qdrant-client, plotly, python-jose[cryptography],
                           psycopg2-binary>=2.9
```

## Build / run / test
```bash
# Install dependencies (activate venv first)
pip install -r requirements.txt

# Run dev server
uvicorn app.main:app --reload

# Run tests
pytest tests/

# Apply DB migrations (requires .env with SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY)
python app/db/apply.py app/db/schema.sql
python app/db/apply.py app/db/policies.sql
python app/db/apply.py app/db/triggers.sql
```

## Environment variables (`.env`)
```
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_JWT_SECRET=
GEMINI_API_KEY=
QDRANT_URL=
QDRANT_API_KEY=
WEB_SEARCH_API_KEY=
DEBUG=false
```

## What is done vs. TODO

### ✅ Done
- **Database:** Full schema (12 tables), RLS policies, triggers, SQL migration runner
- **Auth — session & logout:** JWT verification, HttpOnly session cookie, `POST /auth/logout` with `?logged_out=1` banner (Step 01/02)
- **Auth — server-side login:** `POST /auth/login` — uses `anon_client()` for sign-in, HttpOnly `access_token` cookie set server-side (Step 04)
- **Auth — registration:** `GET /register` + `POST /register` — admin API with `email_confirm=True`; email verification disabled (Step 03)
- **Auth — redirect guards:** `optional_user()` dependency; `GET /login` and `GET /register` redirect authenticated users to dashboard; all protected SSR routes redirect unauthenticated users to `/login?next=<path>` with open-redirect prevention (Step 04)
- **Auth — no Supabase JS:** neither `login.html` nor `register.html` loads the Supabase JS SDK or exposes any key to the browser; all sign-in/sign-up is server-side (Steps 03–04)
- **App scaffold:** FastAPI app, all routers wired, Jinja2 templates, static mount
- **Config:** pydantic-settings loading from `.env`
- **Supabase clients:** anon + service_role, correctly scoped
- **Intake models:** All Pydantic models with Decimal money fields
- **Report models:** TaxResult, Allocation, GoalFunding, EngineOutput, AINarrative
- **Tax engine (new regime):** AY 2026-27 slabs, 87A rebate, cess — unit-tested
- **Allocation engine:** current_allocation from holdings, target by risk profile
- **Engine runner:** run_engine() wires tax + allocation + goals
- **Background worker:** generate_report() — engine → AI degrade path → DB writes
- **AI subsystem:** All modules scaffolded (web_search, rag, gemini, prompts, validation, orchestrator)
- **Worker DB writes:** tax_reports + investment_plans via service_role
- **Dashboard routes:** GET /dashboard (optional_user redirect, `authenticated=True`) + job status poll endpoint
- **Onboarding routes:** GET /onboarding/{step} (optional_user redirect, `authenticated=True`) + POST /submit with job enqueue
- **Test suite:** 33 tests across test_tax.py, test_auth.py, test_registration.py, test_login_logout.py — all green

### 🔲 TODO (next steps)
- **Old-regime tax:** implement slabs + 80C/80D/HRA deductions in `compute_old_regime()`
- **Onboarding templates:** full multi-step HTML forms for all 8 steps (only demographics placeholder exists)
- **Partial state persistence:** server-side session store for in-progress form data across steps
- **Input versioning:** auto-increment `version` per user (currently hardcoded to `1`)
- **Normalized fan-out:** write income_sources, expenses, liabilities, holdings, insurance_policies, goals from intake submission
- **Goals engine:** implement real goal-funding math in `evaluate_goal()`
- **Plotly figures:** implement allocation + tax figure builders in `charts/figures.py`; wire into dashboard template
- **Dashboard SSE/poll:** frontend JS to poll `/jobs/{job_id}/status` and refresh on complete
- **RAG corpus:** ingest tax & portfolio PDFs into Qdrant collections
- **Profile creation:** auto-create `profiles` row on first login (DB trigger or post-login hook)

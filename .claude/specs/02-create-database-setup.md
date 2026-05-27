# Spec: Create Database Setup

## Overview
Completes and applies the full Supabase database configuration for MoneySaarthi. The schema
skeleton (`app/db/schema.sql`) and a partial policies file (`app/db/policies.sql`) already
exist as scaffolding, but three gaps remain before any feature can safely run against a real
database: (1) the RLS policies file only covers `holdings`, `tax_reports`, `investment_plans`,
and `report_jobs` — every other intake table is missing policies; (2) there is no
`profiles` auto-creation trigger so new sign-ups land without a profile row; (3) the
`market_data_cache` table described in §C.1 of the architecture is absent; and (4) there
is no apply script to run the SQL files against Supabase in a reproducible order. This step
closes all four gaps and adds a thin database health check so CI and local setup can verify
connectivity before any application code runs.

## Depends on
**Step 01 — Create Login Page.** Supabase Auth must be configured and the anon/service-role
keys must be present in `.env` before any SQL can be executed against the project.

## Architecture phase
**Capture** — database setup is the prerequisite infrastructure for all three phases
(Capture writes financial inputs, Compute writes reports, Render reads them).

## Routes
- `GET /health/db` — runs a lightweight connectivity probe (`SELECT 1` via the anon client)
  and returns `{"db": "ok"}` or `{"db": "error", "detail": "..."}` (HTTP 200 either way) —
  public (no auth required; used by deployment health checks)

## Database changes

### New table — `market_data_cache`
Caches Web-Search Agent results keyed by `(tool, params, date)` per §C.1:

```sql
create table if not exists public.market_data_cache (
    id            uuid primary key default gen_random_uuid(),
    tool          text not null,                   -- e.g. 'search_top_funds'
    params        jsonb not null,                  -- tool call parameters
    cache_date    date not null default current_date,
    result        jsonb not null,                  -- scraped structured JSON
    source_urls   text[],                          -- cited sources
    fetched_at    timestamptz not null default now(),
    unique (tool, params, cache_date)
);
create index if not exists idx_market_data_cache_date on public.market_data_cache (cache_date);
-- No RLS: this table contains only public market data, no PII.
-- Worker writes via service_role; reads can use anon key.
```

### New trigger — auto-create `profiles` on sign-up
Ensures every new `auth.users` row immediately gets a matching `profiles` row:

```sql
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
    insert into public.profiles (id, full_name)
    values (new.id, new.raw_user_meta_data ->> 'full_name')
    on conflict (id) do nothing;
    return new;
end;
$$;

create or replace trigger on_auth_user_created
    after insert on auth.users
    for each row execute procedure public.handle_new_user();
```

### Complete RLS policies
`app/db/policies.sql` currently shows only `holdings`, `tax_reports`, `investment_plans`,
and `report_jobs` as concrete policies. All other tables need the same pattern added:
- `household_members` — full CRUD (select / insert / update / delete)
- `financial_inputs` — full CRUD
- `income_sources` — full CRUD
- `expenses` — full CRUD
- `liabilities` — full CRUD
- `insurance_policies` — full CRUD
- `goals` — full CRUD

No changes to the existing `profiles`, `tax_reports`, `investment_plans`, or `report_jobs`
policies — those are already correct.

`market_data_cache` intentionally has **no** RLS (public market data, no PII).

### No other schema changes
All nine domain tables in `app/db/schema.sql` are complete and match §B.2 exactly.

## Pydantic models
- **Create:** None
- **Modify:** None — this step is pure infrastructure (SQL + a single health route)

## Templates
- **Create:** None
- **Modify:** None

## Engine / AI changes
None. The deterministic engine and AI subsystem are untouched in this step.

## Files to change
- `app/db/schema.sql` — add `market_data_cache` table DDL and its index
- `app/db/policies.sql` — add full CRUD policies for all seven remaining intake tables;
  keep existing policies unchanged
- `app/routers/templates.py` — **rename / move** the `GET /health/db` route here if it
  fits, **or** add a `app/routers/health.py` router and mount it in `app/main.py`
- `app/main.py` — include the health router

## Files to create
- `app/db/triggers.sql` — `handle_new_user` function + `on_auth_user_created` trigger
- `app/db/apply.py` — Python script that reads `schema.sql`, `policies.sql`, and
  `triggers.sql` in order and executes them against the Supabase database using the
  `service_role` key via `psycopg2` (or the Supabase Management API). Accepts a
  `--dry-run` flag that prints SQL without executing. Idempotent: all DDL uses
  `create … if not exists` / `create or replace`. Prints a summary of statements executed.
- `app/routers/health.py` — FastAPI router with the `GET /health/db` probe

## New dependencies
- `psycopg2-binary` — used by `app/db/apply.py` to execute raw SQL against the Supabase
  Postgres connection string (`DATABASE_URL` env var). Not imported by the FastAPI app
  itself; only by the apply script.

Add to `requirements.txt`:
```
psycopg2-binary>=2.9
```

## Rules for implementation
- Use `Decimal` for all money math — never float
- Tax rules must live in `app/engine/tax/rules.py`, keyed by assessment year
- Gemini writes narrative only; it must never compute or invent a rupee figure
- After Gemini responds, run the numeric-consistency check in `app/ai/validation.py`
- RLS is enforced on every table; derive `user_id` from the Supabase JWT only
- `service_role` key is used only in the background worker and `app/db/apply.py` — never
  in templates or client bundles
- Plotly figures are built server-side, serialized with `pio.to_json`, hydrated client-side
  with `Plotly.newPlot` — no iframes or static images
- All templates extend `app/templates/base.html`
- The `handle_new_user` trigger function must use `security definer` so it can write to
  `public.profiles` regardless of the caller's role; pin `search_path = public` to prevent
  search-path injection attacks
- `app/db/apply.py` must be **idempotent** — running it twice must produce no errors and
  no duplicate state (`create … if not exists`, `create or replace`)
- The `DATABASE_URL` env var (Supabase direct connection string, **not** the REST URL)
  must be added to `.env.example` alongside the existing vars; the actual value stays in
  `.env` (git-ignored)
- The `GET /health/db` route must use the **anon client** (not service_role) so it
  validates the connection path the application layer actually uses
- `market_data_cache` has no RLS because it holds only public market data with no PII;
  document this decision in a SQL comment
- All new RLS policies must use `with check` on insert/update to prevent `user_id` spoofing
- Index `user_id` on every table — already done in `schema.sql`; verify no index is missing
  after adding `market_data_cache`

## Definition of done
- [ ] `python app/db/apply.py` runs without errors against the Supabase project and
      prints a summary of statements executed
- [ ] Running `python app/db/apply.py` a second time is fully idempotent (no errors, no
      duplicates)
- [ ] `python app/db/apply.py --dry-run` prints all SQL statements without executing them
- [ ] `GET /health/db` returns HTTP 200 with `{"db": "ok"}` when the database is reachable
- [ ] Registering a new Supabase user (via the existing `/auth/session` flow) results in a
      `profiles` row being auto-created with the matching `id` (verifiable in the Supabase
      dashboard Table Editor or via `SELECT * FROM profiles WHERE id = '<new-user-uuid>'`)
- [ ] A test user cannot read another user's `financial_inputs` rows when querying via the
      anon key with their own JWT (RLS blocks cross-user access)
- [ ] `SELECT * FROM market_data_cache` is accessible from the anon client without a JWT
      (confirming no RLS on that table)
- [ ] `app/db/schema.sql`, `app/db/policies.sql`, and `app/db/triggers.sql` contain no
      TODO or placeholder comments — every table is fully covered
- [ ] `.env.example` contains a `DATABASE_URL` entry with a descriptive placeholder value
- [ ] `tests/test_db_setup.py` passes: at minimum tests that (a) `apply.py --dry-run`
      exits 0 and produces non-empty output, and (b) the `/health/db` endpoint returns
      `{"db": "ok"}` when `SUPABASE_URL` and `SUPABASE_ANON_KEY` are present

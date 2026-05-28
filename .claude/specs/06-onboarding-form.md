# Spec: Onboarding Form

## Overview
The onboarding form is the primary data-capture interface for MoneySaarthi — the multi-step
household financial intake that feeds the deterministic engine and ultimately the AI advisory
report. This step replaces the single demographics placeholder with fully-functional HTML forms
for all eight onboarding steps (Demographics → Income → Expenses → Loans →
Savings/Investments → Insurance → Goals → Risk), implements server-side partial-state
persistence so a refresh or navigation never loses a half-entered sheet, adds `POST /{step}`
endpoints that validate and advance the user through the funnel, and wires the final submit to
the existing `POST /submit` endpoint. The result is Phase 1 (Capture) of the three-phase
pipeline described in §A.3 of the architecture.

## Depends on
- Step 01 — Login page (auth cookie + `optional_user` / `current_user` dependencies)
- Step 02 — Database setup (`financial_inputs`, `income_sources`, `expenses`, `liabilities`,
  `holdings`, `insurance_policies`, `goals`, `report_jobs` tables + RLS policies)
- Step 03 — User registration
- Step 04 — Login/logout + redirect guards (`authenticated=True` context key)
- Step 05 — Dashboard page (onboarding final-submit redirects to `/dashboard?job=<id>`)

## Architecture phase
Capture (§A.3 Phase 1)

## Routes
Existing routes modified, one new route added:

- `GET /onboarding/{step}` — render step page pre-filled from draft state — authenticated
  *(existing; modify to load draft from DB)*
- `POST /onboarding/{step}` — validate step payload, merge into draft, redirect to next step — authenticated
  *(new)*
- `POST /onboarding/submit` — validate full `IntakeSubmission`, write `financial_inputs`,
  fan out normalized rows, enqueue job, redirect to dashboard — authenticated
  *(existing; add normalized fan-out + auto-increment version)*

## Database changes
One new table for server-side partial-state persistence:

```sql
-- ONBOARDING_DRAFTS: server-side partial form state, one row per user
create table if not exists public.onboarding_drafts (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null unique references auth.users(id) on delete cascade,
    draft       jsonb not null default '{}'::jsonb,
    updated_at  timestamptz not null default now()
);

alter table public.onboarding_drafts enable row level security;

create policy "own draft - select" on public.onboarding_drafts
    for select using ( auth.uid() = user_id );
create policy "own draft - insert" on public.onboarding_drafts
    for insert with check ( auth.uid() = user_id );
create policy "own draft - update" on public.onboarding_drafts
    for update using ( auth.uid() = user_id ) with check ( auth.uid() = user_id );
create policy "own draft - delete" on public.onboarding_drafts
    for delete using ( auth.uid() = user_id );

create index if not exists onboarding_drafts_user_id_idx on public.onboarding_drafts (user_id);
```

The `draft` JSONB column accumulates the user's step payloads as they progress, keyed by step
name (`"demographics"`, `"income"`, etc.). On final submit the assembled draft is validated as
`IntakeSubmission` and then cleared.

**Existing tables modified:**
- `financial_inputs`: no column change; the `version` value is now auto-incremented per user
  (query `max(version)` for the user and add 1 rather than hardcoding `1`).

## Pydantic models
- **Create:**
  - `app/models/onboarding.py` — step-level partial Pydantic models for per-step POST
    validation (separate from the full `IntakeSubmission` so partial submits don't fail for
    missing later steps):
    - `DemographicsStep` — `members: list[HouseholdMember]`
    - `IncomeStep` — `incomes: list[IncomeSource]`
    - `ExpensesStep` — `expenses: list[Expense]`
    - `LoansStep` — `liabilities: list[Liability]`
    - `InvestmentsStep` — `holdings: list[Holding]`
    - `InsuranceStep` — `insurance: list[InsurancePolicy]`
    - `GoalsStep` — `goals: list[Goal]`
    - `RiskStep` — `risk_appetite: Literal["Conservative", "Moderate", "Aggressive"]`
    - `StepUnion` — `Union[DemographicsStep, IncomeStep, ..., RiskStep]`
      (used in the router for dispatch)

- **Modify:** None (existing `IntakeSubmission` and sub-models in `app/models/intake.py`
  remain unchanged).

## Templates
- **Create:**
  - `app/templates/onboarding/income.html` — income sources form (Sir + Mam earners,
    multiple source rows, "Add another" dynamic rows via plain JS)
  - `app/templates/onboarding/expenses.html` — expenses form (household, hospital, school,
    discretionary, guest, business categories)
  - `app/templates/onboarding/loans.html` — liabilities form (home, personal, car, other;
    owner dropdown, EMI, pending amount, interest rate, duration)
  - `app/templates/onboarding/investments.html` — holdings form (asset class selector,
    instrument name, owner, SIP monthly, invested amount, current corpus, interest rate)
  - `app/templates/onboarding/insurance.html` — insurance policies form (life, health,
    corporate life, corporate health; structure, insured, premium, frequency, end date,
    maturity amount)
  - `app/templates/onboarding/goals.html` — goals form (goal name, horizon type, duration
    years, amount required today)
  - `app/templates/onboarding/risk.html` — risk profile step (single radio group:
    Conservative / Moderate / Aggressive; brief description of each)

- **Modify:**
  - `app/templates/onboarding/demographics.html` — replace placeholder skeleton with the
    full household-member form (Sir, Mam, children, dependent parents). Show server-side
    errors. Pre-populate fields from draft if available.
  - All onboarding templates — add a step-progress indicator nav (showing current step out
    of 8 and links back to completed steps), Back button (GET to previous step), and a
    "Save & Continue" primary button that POSTs to `/onboarding/{step}`.

  ### Common template structure (all 8 steps)
  ```
  {% extends "base.html" %}
  {% block title %}MoneySaarthi — {{ step_label }}{% endblock %}
  {% block content %}
    <!-- Progress bar: step N of 8 -->
    <!-- Error banner if errors exist -->
    <form method="post" action="/onboarding/{{ step }}">
      <!-- step-specific fields -->
      <div class="form-actions">
        {% if step != 'demographics' %}
          <a href="/onboarding/{{ prev_step }}" class="btn-secondary">Back</a>
        {% endif %}
        <button type="submit" class="btn-primary">
          {% if step == 'risk' %}Generate Report{% else %}Save & Continue{% endif %}
        </button>
      </div>
    </form>
  {% endblock %}
  ```

  ### Multi-row input pattern (income, loans, holdings, insurance, goals)
  Repeat a named field group using indexed names: `incomes[0][earner]`,
  `incomes[0][source_type]`, `incomes[0][monthly_amount]`, `incomes[1][earner]`, etc.
  An "Add row" button appends a new fieldset via plain JS (no framework).
  On server-side parsing, collect all indexed groups into a list before constructing
  the step Pydantic model.

## Engine / AI changes
None. The deterministic engine and AI subsystem are not touched by this step. Compute and
render phases are unchanged.

## Files to change

| File | What changes |
|------|-------------|
| `app/routers/onboarding.py` | Add `POST /{step}` handler (validate step, merge draft, redirect to next); modify `GET /{step}` to pre-fill from draft; modify `POST /submit` to auto-increment version + fan out normalized rows; add `_next_step()` / `_prev_step()` helpers |
| `app/templates/onboarding/demographics.html` | Replace placeholder with full form + progress bar + error display + pre-fill |
| `app/static/app.css` | Onboarding form layout classes: `onboarding-progress`, `step-form`, `field-group`, `repeating-row`, `add-row-btn`, `form-error`, `form-actions` |
| `app/db/schema.sql` | Append `onboarding_drafts` table DDL |
| `app/db/policies.sql` | Append RLS policies for `onboarding_drafts` |

## Files to create

| File | Purpose |
|------|---------|
| `app/models/onboarding.py` | Per-step Pydantic models for step-level partial validation |
| `app/templates/onboarding/income.html` | Income sources form |
| `app/templates/onboarding/expenses.html` | Expenses form |
| `app/templates/onboarding/loans.html` | Liabilities form |
| `app/templates/onboarding/investments.html` | Holdings form |
| `app/templates/onboarding/insurance.html` | Insurance policies form |
| `app/templates/onboarding/goals.html` | Financial goals form |
| `app/templates/onboarding/risk.html` | Risk profile selection |
| `tests/test_onboarding.py` | Integration tests — see Definition of Done |

## New dependencies
No new dependencies.

## Rules for implementation
- Use `Decimal` for all money math — never float
- Tax rules must live in `app/engine/tax/rules.py`, keyed by assessment year
- Gemini writes narrative only; it must never compute or invent a rupee figure
- After Gemini responds, run the numeric-consistency check in `app/ai/validation.py`
- RLS is enforced on every table; derive `user_id` from the Supabase JWT only
- `service_role` key is used only in the background worker — never in templates
- Plotly figures are built server-side, serialized with `pio.to_json`, hydrated
  client-side with `Plotly.newPlot` — no iframes or static images
- All templates extend `app/templates/base.html`
- `user_id` in `onboarding_drafts` must be set from the verified JWT, not the request body
- All form `POST` handlers must call `optional_user` / `current_user` and redirect to
  `/login?next=/onboarding/{step}` when unauthenticated — never store data for an
  unauthenticated request
- Draft data is merged (not replaced) on each step POST: existing keys from previous steps
  are preserved; only the current step's keys are overwritten
- The full `IntakeSubmission` is only validated on `POST /submit` — per-step POSTs use
  the lighter step models so partial form saves never fail for missing later-step fields
- `POST /submit` must reject (422) if the assembled draft is missing required fields;
  the final step (risk) is the natural gate but the submit endpoint is the last safety net
- Normalized fan-out in `POST /submit` must use the `anon_client()` for
  `financial_inputs` (RLS enforced); the existing worker uses `service_client()` for
  `tax_reports`/`investment_plans` (this does not change)
- After a successful final submit, delete the `onboarding_drafts` row for the user so a
  repeat visit starts a fresh intake
- Auto-increment `version`: query `max(version)` for the user from `financial_inputs` and
  add 1 (default to 1 if no prior row exists)
- Cross-field validation to surface as form errors (not 500s): total EMI > 80% of total
  income → warn; `current_corpus < invested_amount` on any holding → warn; term policy
  with `maturity_amount > 0` → warn
- The progress bar must be rendered server-side (not computed in JS) by passing `step_index`
  and `total_steps` (8) in every template context

## Definition of done
- [ ] `GET /onboarding/demographics` returns 200 HTML with a form containing fields for
  member role, display name, age, and financially dependent checkbox; page shows
  step 1 of 8 in the progress indicator
- [ ] `POST /onboarding/demographics` with valid data redirects 302 to
  `/onboarding/income`; draft is saved in `onboarding_drafts` for the user
- [ ] `GET /onboarding/income` after a demographics POST pre-fills the income form from
  the saved draft (fields are populated in the HTML)
- [ ] `POST /onboarding/{step}` with missing required fields (e.g. negative monthly amount)
  returns 200 with the form re-rendered and field-level error messages visible
- [ ] All 8 step GET endpoints return 200 with the correct template (no 500 for missing
  template)
- [ ] All 8 step POST endpoints return 302 redirect to the next step on valid data
- [ ] `POST /onboarding/risk` (final step) with valid data redirects to the submit endpoint
  which in turn redirects to `/dashboard?job=<id>`
- [ ] `POST /submit` inserts a `financial_inputs` row with version auto-incremented (version
  2 on second submission for the same user)
- [ ] `POST /submit` fans out rows into `income_sources`, `expenses`, `liabilities`,
  `holdings`, `insurance_policies`, and `goals` tables with correct `user_id` and `input_id`
- [ ] `onboarding_drafts` row is deleted after a successful final submit
- [ ] `GET /onboarding/{step}` without auth cookie → 302 to `/login?next=/onboarding/{step}`
- [ ] `POST /onboarding/{step}` without auth cookie → 302 to `/login?next=/onboarding/{step}`
- [ ] Back button on step 3+ is a `GET` link to the previous step (not a POST)
- [ ] Risk profile step shows Conservative / Moderate / Aggressive radio inputs; selecting
  one and submitting completes the funnel
- [ ] All 33 existing tests still pass
- [ ] `pytest tests/test_onboarding.py -v` — all new onboarding tests pass

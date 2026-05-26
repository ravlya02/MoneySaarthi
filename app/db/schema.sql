-- MoneySaarthi schema. Source of truth: documents/architecture.md §B.
-- Run against the Supabase Postgres instance. RLS enabled on every table.

-- 1. PROFILES: 1:1 extension of auth.users
create table if not exists public.profiles (
    id            uuid primary key references auth.users(id) on delete cascade,
    full_name     text,
    household_name text,
    risk_appetite text check (risk_appetite in ('Conservative','Moderate','Aggressive')),
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

-- 2. HOUSEHOLD MEMBERS
create table if not exists public.household_members (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null references auth.users(id) on delete cascade,
    member_role   text not null,
    display_name  text,
    age           numeric(5,1),
    studies_in_class text,
    financially_dependent boolean default false,
    created_at    timestamptz not null default now()
);

-- 3. FINANCIAL_INPUTS: versioned raw submission
create table if not exists public.financial_inputs (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null references auth.users(id) on delete cascade,
    version       int  not null default 1,
    raw_payload   jsonb not null,
    submitted_at  timestamptz not null default now(),
    unique (user_id, version)
);

-- 4a. INCOME_SOURCES
create table if not exists public.income_sources (
    id          uuid primary key default gen_random_uuid(),
    input_id    uuid not null references public.financial_inputs(id) on delete cascade,
    user_id     uuid not null references auth.users(id) on delete cascade,
    earner      text not null,
    source_type text not null,
    monthly_amount numeric(14,2) not null default 0,
    annual_amount  numeric(14,2) generated always as (monthly_amount * 12) stored
);

-- 4b. EXPENSES
create table if not exists public.expenses (
    id          uuid primary key default gen_random_uuid(),
    input_id    uuid not null references public.financial_inputs(id) on delete cascade,
    user_id     uuid not null references auth.users(id) on delete cascade,
    category    text not null,
    monthly_amount numeric(14,2) not null default 0
);

-- 4c. LIABILITIES
create table if not exists public.liabilities (
    id            uuid primary key default gen_random_uuid(),
    input_id      uuid not null references public.financial_inputs(id) on delete cascade,
    user_id       uuid not null references auth.users(id) on delete cascade,
    loan_type     text not null,
    owner         text,
    emi           numeric(14,2) default 0,
    pending_amount numeric(16,2) default 0,
    interest_rate numeric(5,2),
    duration_months int
);

-- 4d. HOLDINGS
create table if not exists public.holdings (
    id            uuid primary key default gen_random_uuid(),
    input_id      uuid not null references public.financial_inputs(id) on delete cascade,
    user_id       uuid not null references auth.users(id) on delete cascade,
    asset_class   text not null,
    instrument    text not null,
    owner         text,
    sip_monthly   numeric(14,2) default 0,
    invested_amount numeric(16,2) default 0,
    current_corpus  numeric(16,2) default 0,
    interest_rate numeric(5,2)
);

-- 4e. INSURANCE
create table if not exists public.insurance_policies (
    id            uuid primary key default gen_random_uuid(),
    input_id      uuid not null references public.financial_inputs(id) on delete cascade,
    user_id       uuid not null references auth.users(id) on delete cascade,
    policy_type   text not null,
    product_name  text,
    structure     text,
    insured       text,
    premium       numeric(14,2),
    premium_frequency text,
    policy_end_date date,
    maturity_amount numeric(16,2)
);

-- 4f. GOALS
create table if not exists public.goals (
    id            uuid primary key default gen_random_uuid(),
    input_id      uuid not null references public.financial_inputs(id) on delete cascade,
    user_id       uuid not null references auth.users(id) on delete cascade,
    goal_name     text not null,
    horizon_type  text,
    duration_years numeric(5,1),
    amount_required_today numeric(16,2)
);

-- 5. INVESTMENT_PLANS: engine output
create table if not exists public.investment_plans (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null references auth.users(id) on delete cascade,
    input_version int  not null,
    target_equity_pct      numeric(5,2),
    target_debt_pct        numeric(5,2),
    target_realestate_pct  numeric(5,2),
    target_metals_pct      numeric(5,2),
    plan_detail   jsonb not null,
    generated_at  timestamptz not null default now()
);

-- 6. TAX_REPORTS: engine output + Gemini narrative
create table if not exists public.tax_reports (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null references auth.users(id) on delete cascade,
    input_version int  not null,
    assessment_year text not null default 'AY 2026-27',
    old_regime_tax  numeric(14,2),
    new_regime_tax  numeric(14,2),
    recommended_regime text,
    breakdown     jsonb not null,
    ai_narrative  text,
    ai_action_items jsonb,
    generated_at  timestamptz not null default now()
);

-- 7. REPORT_JOBS: async generation tracking
create table if not exists public.report_jobs (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null references auth.users(id) on delete cascade,
    input_version int not null,
    status        text not null default 'queued'
                  check (status in ('queued','running','complete','failed')),
    error_detail  text,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

-- Indexes: user_id is an RLS filter on essentially every query.
create index if not exists idx_household_members_user on public.household_members (user_id);
create index if not exists idx_financial_inputs_user on public.financial_inputs (user_id);
create index if not exists idx_income_sources_user on public.income_sources (user_id);
create index if not exists idx_expenses_user on public.expenses (user_id);
create index if not exists idx_liabilities_user on public.liabilities (user_id);
create index if not exists idx_holdings_user on public.holdings (user_id);
create index if not exists idx_insurance_policies_user on public.insurance_policies (user_id);
create index if not exists idx_goals_user on public.goals (user_id);
create index if not exists idx_investment_plans_user on public.investment_plans (user_id);
create index if not exists idx_tax_reports_user on public.tax_reports (user_id);
create index if not exists idx_report_jobs_user on public.report_jobs (user_id);

-- Row-Level Security. See policies.sql for per-table policies.
alter table public.profiles            enable row level security;
alter table public.household_members   enable row level security;
alter table public.financial_inputs    enable row level security;
alter table public.income_sources      enable row level security;
alter table public.expenses            enable row level security;
alter table public.liabilities         enable row level security;
alter table public.holdings            enable row level security;
alter table public.insurance_policies  enable row level security;
alter table public.goals               enable row level security;
alter table public.investment_plans    enable row level security;
alter table public.tax_reports         enable row level security;
alter table public.report_jobs         enable row level security;

-- RLS policies. Source of truth: documents/architecture.md §B.3.
-- Rule: a user can only touch rows where user_id = auth.uid().
-- Reports (tax_reports / investment_plans) are READ-ONLY to the user; only the
-- service_role worker writes them (it bypasses RLS by design).

-- Profiles: a user owns exactly their row (id == auth.uid())
create policy "own profile - select" on public.profiles
    for select using ( auth.uid() = id );
create policy "own profile - insert" on public.profiles
    for insert with check ( auth.uid() = id );
create policy "own profile - update" on public.profiles
    for update using ( auth.uid() = id ) with check ( auth.uid() = id );

-- Full CRUD for the owner on user-scoped intake tables.
-- Repeat this block for: household_members, financial_inputs, income_sources,
-- expenses, liabilities, holdings, insurance_policies, goals.
-- Example shown for holdings:
create policy "own holdings - select" on public.holdings
    for select using ( auth.uid() = user_id );
create policy "own holdings - insert" on public.holdings
    for insert with check ( auth.uid() = user_id );
create policy "own holdings - update" on public.holdings
    for update using ( auth.uid() = user_id ) with check ( auth.uid() = user_id );
create policy "own holdings - delete" on public.holdings
    for delete using ( auth.uid() = user_id );

-- Reports: read-only to the user. No insert/update/delete policy — the worker
-- writes via service_role.
create policy "own tax_report - select" on public.tax_reports
    for select using ( auth.uid() = user_id );
create policy "own investment_plan - select" on public.investment_plans
    for select using ( auth.uid() = user_id );
create policy "own report_job - select" on public.report_jobs
    for select using ( auth.uid() = user_id );

-- Household members: full CRUD for the owner.
create policy "own household_members - select" on public.household_members
    for select using ( auth.uid() = user_id );
create policy "own household_members - insert" on public.household_members
    for insert with check ( auth.uid() = user_id );
create policy "own household_members - update" on public.household_members
    for update using ( auth.uid() = user_id ) with check ( auth.uid() = user_id );
create policy "own household_members - delete" on public.household_members
    for delete using ( auth.uid() = user_id );

-- Financial inputs: full CRUD for the owner.
create policy "own financial_inputs - select" on public.financial_inputs
    for select using ( auth.uid() = user_id );
create policy "own financial_inputs - insert" on public.financial_inputs
    for insert with check ( auth.uid() = user_id );
create policy "own financial_inputs - update" on public.financial_inputs
    for update using ( auth.uid() = user_id ) with check ( auth.uid() = user_id );
create policy "own financial_inputs - delete" on public.financial_inputs
    for delete using ( auth.uid() = user_id );

-- Income sources: full CRUD for the owner.
create policy "own income_sources - select" on public.income_sources
    for select using ( auth.uid() = user_id );
create policy "own income_sources - insert" on public.income_sources
    for insert with check ( auth.uid() = user_id );
create policy "own income_sources - update" on public.income_sources
    for update using ( auth.uid() = user_id ) with check ( auth.uid() = user_id );
create policy "own income_sources - delete" on public.income_sources
    for delete using ( auth.uid() = user_id );

-- Expenses: full CRUD for the owner.
create policy "own expenses - select" on public.expenses
    for select using ( auth.uid() = user_id );
create policy "own expenses - insert" on public.expenses
    for insert with check ( auth.uid() = user_id );
create policy "own expenses - update" on public.expenses
    for update using ( auth.uid() = user_id ) with check ( auth.uid() = user_id );
create policy "own expenses - delete" on public.expenses
    for delete using ( auth.uid() = user_id );

-- Liabilities: full CRUD for the owner.
create policy "own liabilities - select" on public.liabilities
    for select using ( auth.uid() = user_id );
create policy "own liabilities - insert" on public.liabilities
    for insert with check ( auth.uid() = user_id );
create policy "own liabilities - update" on public.liabilities
    for update using ( auth.uid() = user_id ) with check ( auth.uid() = user_id );
create policy "own liabilities - delete" on public.liabilities
    for delete using ( auth.uid() = user_id );

-- Insurance policies: full CRUD for the owner.
create policy "own insurance_policies - select" on public.insurance_policies
    for select using ( auth.uid() = user_id );
create policy "own insurance_policies - insert" on public.insurance_policies
    for insert with check ( auth.uid() = user_id );
create policy "own insurance_policies - update" on public.insurance_policies
    for update using ( auth.uid() = user_id ) with check ( auth.uid() = user_id );
create policy "own insurance_policies - delete" on public.insurance_policies
    for delete using ( auth.uid() = user_id );

-- Goals: full CRUD for the owner.
create policy "own goals - select" on public.goals
    for select using ( auth.uid() = user_id );
create policy "own goals - insert" on public.goals
    for insert with check ( auth.uid() = user_id );
create policy "own goals - update" on public.goals
    for update using ( auth.uid() = user_id ) with check ( auth.uid() = user_id );
create policy "own goals - delete" on public.goals
    for delete using ( auth.uid() = user_id );

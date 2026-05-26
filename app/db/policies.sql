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

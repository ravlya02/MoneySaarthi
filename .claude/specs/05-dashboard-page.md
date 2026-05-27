# Spec: Dashboard Page

## Overview
The dashboard is the primary post-login destination — it presents the user's
completed financial plan in a structured, visual layout. Four sub-problems must
be solved together: (1) the route must wire the existing Plotly figure builders
and pass `alloc_fig` / `tax_fig` to the template so charts actually render;
(2) `dashboard.html` must be replaced with a fully styled layout showing tax
numbers, AI narrative, action items, and goal-funding rows; (3) the pending
state must reliably pass the `job_id` to the template so polling works even
when the user navigates directly to `/dashboard` without the `?job=` URL
parameter; and (4) dashboard-specific CSS must be added to `app.css` so the
page is usable on first load.

## Depends on
- Step 01 — Login page (auth cookie in place)
- Step 02 — Database setup (tax_reports, investment_plans, report_jobs tables)
- Step 03 — User registration
- Step 04 — Login/logout + redirect guards (`optional_user`, `authenticated=True`)

## Architecture phase
Render (§A.3 Phase 3)

## Routes
No new routes. The two existing routes in `app/routers/dashboard.py` are
modified but not replaced:

- `GET /dashboard` — serve completed report or pending page — authenticated
- `GET /jobs/{job_id}/status` — JSON poll endpoint — authenticated (unchanged)

## Database changes
No database changes. All data already lives in `tax_reports`,
`investment_plans`, and `report_jobs`.

## Pydantic models
- **Create:** None
- **Modify:** None

## Templates
- **Modify:** `app/templates/dashboard.html` — complete redesign (see below)
- **Modify:** `app/templates/dashboard_pending.html` — pass `job_id` from
  context, add spinner and failed-state handling

### `dashboard.html` layout (sections in order)
1. **Page heading** — "Your Financial Plan" + report generation date
2. **Tax summary card** — old-regime vs new-regime tax amounts (₹ formatted);
   recommended-regime badge (green "New Regime" or amber "Old Regime"); the
   two figures are from `report.old_regime_tax` and `report.new_regime_tax`
   (already verified engine numbers — never recomputed here)
3. **AI narrative** — `report.ai_narrative` prose block; hidden if `None`
4. **Action items** — `report.ai_action_items` list; each item shows `action`,
   `instrument` (if set), and `rationale`; section hidden if list is empty
5. **Asset allocation chart** — `<div id="allocChart">` hydrated via
   `alloc_fig` (Plotly donut of target allocation)
6. **Tax comparison chart** — `<div id="taxChart">` hydrated via `tax_fig`
   (Plotly bar: old vs new regime)
7. **Goal funding rows** (if any) — from `plan.plan_detail.goal_funding`;
   each row shows goal name, status badge (on-track / shortfall / surplus),
   monthly SIP suggestion
8. **Disclaimer** — existing `.disclaimer` class text (unchanged)

### `dashboard_pending.html` changes
- Add `{% set job_id = job_id | default('') %}` at top
- JS `jobId` now prefers template variable, falls back to URL param:
  ```js
  const jobId = "{{ job_id }}" || new URLSearchParams(location.search).get('job');
  ```
- Show distinct UI for `status === 'failed'`: red banner with error text
  (fetched from JSON response's `error_detail`)
- Add CSS spinner animation (keyframe in app.css)

## Engine / AI changes
None. Engine and AI modules are not touched. All numbers in the template
originate from `tax_reports` and `investment_plans` DB rows that were written
by the worker.

## Files to change

| File | What changes |
|------|-------------|
| `app/routers/dashboard.py` | Wire figures; look up latest job for pending state; pass `alloc_fig`, `tax_fig`, `plan`, `job_id` to template context |
| `app/charts/figures.py` | No logic change; import path verified |
| `app/templates/dashboard.html` | Full styled redesign |
| `app/templates/dashboard_pending.html` | Prefer context `job_id`; spinner; failed state |
| `app/static/app.css` | Dashboard layout classes (card grid, stat card, badge, action-item, spinner) |

## Files to create

| File | Purpose |
|------|---------|
| `tests/test_dashboard.py` | Unit + integration tests — see Definition of Done |

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
- Numbers displayed in the template come exclusively from `tax_reports` /
  `investment_plans` DB columns — never re-derived in Jinja2 or JS
- `alloc_fig` is built from `investment_plans` target allocation percentages;
  cash percent = `100 - equity - debt - realestate - metals`
- `tax_fig` is built from `tax_reports.old_regime_tax` and
  `tax_reports.new_regime_tax`; reconstruct `TaxResult` in the route
- Neither the anon key nor the service_role key may appear in any template

## Definition of done
- [ ] `GET /dashboard` with a completed `tax_reports` row returns 200 HTML
  containing `id="allocChart"` and `id="taxChart"` and both `alloc_fig` and
  `tax_fig` JSON payloads embedded in the page scripts
- [ ] Tax summary card shows `old_regime_tax` and `new_regime_tax` values and
  the `recommended_regime` badge
- [ ] AI narrative block renders when `ai_narrative` is not None; section is
  absent (not empty) when `ai_narrative` is None
- [ ] Action items section renders rows when `ai_action_items` is non-empty;
  absent when empty
- [ ] Goal funding rows render from `plan_detail.goal_funding` if present
- [ ] `GET /dashboard` with no report but a queued/running job returns 200
  HTML for the pending page, with `job_id` embedded in the template context
  (not only in the URL)
- [ ] Pending-page poll JS calls `/jobs/<job_id>/status` every 3 s and
  redirects to `/dashboard` on `complete`
- [ ] Pending page shows a red error banner when `status === 'failed'`
- [ ] `GET /dashboard` with no report and no job returns the pending page
  without a JS poll loop (no `jobId`)
- [ ] `GET /dashboard` without an auth cookie → 302 to `/login?next=/dashboard`
- [ ] `GET /jobs/<id>/status` without a cookie → 401 JSON (not a redirect)
- [ ] All 33 existing tests still pass
- [ ] `pytest tests/test_dashboard.py -v` — all new tests pass

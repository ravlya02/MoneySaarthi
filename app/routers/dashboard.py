"""Dashboard (§A.3 Phase 3). Polls job status; once complete, builds Plotly
figures server-side and renders. Reports render instantly on later logins."""

from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.charts.figures import build_allocation_fig, build_tax_breakdown_fig
from app.config import Settings, get_settings
from app.db.supabase_client import anon_client
from app.dependencies import CurrentUser, current_user, optional_user
from app.models.reports import Allocation, TaxResult
from app.routers.templates import templates

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, settings: Settings = Depends(get_settings)):
    user = optional_user(request, settings)
    if user is None:
        return RedirectResponse("/login?next=/dashboard", status_code=302)

    db = anon_client()
    token = request.cookies.get("access_token", "")
    if token:
        # Directly set user JWT on the PostgREST client so RLS resolves auth.uid()
        # correctly.  Do NOT use db.auth.set_session() — it fires an auth event that
        # resets _postgrest to a new anon-key-only instance.
        db.postgrest.auth(token)
    report_result = (
        db.table("tax_reports")
        .select("*")
        .eq("user_id", user.id)
        .order("generated_at", desc=True)
        .limit(1)
        .execute()
    )

    if not report_result.data:
        # No completed report yet. Check if the user has ever submitted intake data.
        # If not, they are a brand-new user → redirect to onboarding so they fill
        # in their details before a report can be generated.
        inputs_result = (
            db.table("financial_inputs")
            .select("id")
            .eq("user_id", user.id)
            .limit(1)
            .execute()
        )
        if not inputs_result.data:
            return RedirectResponse("/onboarding/demographics", status_code=302)

        # User has submitted data but the report is still generating (or failed).
        # Look up the latest job so we can embed job_id in the template context,
        # so polling works even when the user navigates directly to /dashboard
        # without the ?job= URL parameter.
        job_result = (
            db.table("report_jobs")
            .select("id,status")
            .eq("user_id", user.id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        job_id = job_result.data[0]["id"] if job_result.data else ""
        return templates.TemplateResponse(
            request=request,
            name="dashboard_pending.html",
            context={"job_id": job_id, "authenticated": True},
        )

    report = report_result.data[0]

    # Fetch the matching investment plan (latest for this user).
    plan_result = (
        db.table("investment_plans")
        .select("*")
        .eq("user_id", user.id)
        .order("generated_at", desc=True)
        .limit(1)
        .execute()
    )
    plan = plan_result.data[0] if plan_result.data else None

    # Build Plotly figures from verified DB numbers — never re-derived here (§D.1).
    alloc_fig = None
    if plan:
        equity = Decimal(str(plan["target_equity_pct"]))
        debt   = Decimal(str(plan["target_debt_pct"]))
        re_    = Decimal(str(plan["target_realestate_pct"]))
        metals = Decimal(str(plan["target_metals_pct"]))
        cash   = Decimal("100") - equity - debt - re_ - metals
        alloc  = Allocation(equity=equity, debt=debt, realestate=re_, metals=metals, cash=cash)
        alloc_fig = build_allocation_fig(alloc)

    # Reconstruct TaxResult from DB strings to pass to the figure builder.
    tax_result = TaxResult(
        assessment_year=report["assessment_year"],
        old_regime_tax=Decimal(str(report["old_regime_tax"])),
        new_regime_tax=Decimal(str(report["new_regime_tax"])),
        recommended_regime=report["recommended_regime"],
        breakdown=report.get("breakdown") or {},
    )
    tax_fig = build_tax_breakdown_fig(tax_result)

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "report": report,
            "plan": plan,
            "alloc_fig": alloc_fig,
            "tax_fig": tax_fig,
            "authenticated": True,
        },
    )


@router.get("/jobs/{job_id}/status")
async def job_status(job_id: str, request: Request, user: CurrentUser = Depends(current_user)):
    # JSON endpoint — 401 is the correct response here, not a redirect.
    db = anon_client()
    token = request.cookies.get("access_token", "")
    if token:
        db.postgrest.auth(token)
    row = (
        db.table("report_jobs")
        .select("status,error_detail")
        .eq("id", job_id)
        .eq("user_id", user.id)
        .single()
        .execute()
    )
    return JSONResponse(row.data)

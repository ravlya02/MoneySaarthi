"""Dashboard (§A.3 Phase 3). Polls job status; once complete, builds Plotly
figures server-side and renders. Reports render instantly on later logins."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.db.supabase_client import anon_client
from app.dependencies import CurrentUser, current_user
from app.routers.templates import templates

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: CurrentUser = Depends(current_user)):
    db = anon_client()
    report = db.table("tax_reports").select("*").eq("user_id", user.id).order("generated_at", desc=True).limit(1).execute()
    if not report.data:
        return templates.TemplateResponse(request=request, name="dashboard_pending.html")

    # TODO: build alloc_fig / tax_fig via app.charts.figures and pass to template.
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"report": report.data[0]})


@router.get("/jobs/{job_id}/status")
async def job_status(job_id: str, user: CurrentUser = Depends(current_user)):
    db = anon_client()
    row = db.table("report_jobs").select("status,error_detail").eq("id", job_id).eq("user_id", user.id).single().execute()
    return JSONResponse(row.data)

"""Multi-step onboarding form (§A.3 Phase 1, §D.2). Each step persists partial
state server-side so a refresh never loses a half-entered household sheet. Final
submit validates with Pydantic, writes financial_inputs, and enqueues a job."""

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import Settings, get_settings
from app.db.supabase_client import anon_client
from app.dependencies import CurrentUser, current_user, optional_user
from app.models.intake import IntakeSubmission
from app.routers.templates import templates
from app.worker.jobs import generate_report

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

STEPS = ["demographics", "income", "expenses", "loans", "investments", "insurance", "goals", "risk"]


@router.get("/{step}", response_class=HTMLResponse)
async def step_page(step: str, request: Request, settings: Settings = Depends(get_settings)):
    user = optional_user(request, settings)
    if user is None:
        return RedirectResponse(f"/login?next=/onboarding/{step}", status_code=302)
    return templates.TemplateResponse(
        request=request, name=f"onboarding/{step}.html",
        context={"step": step, "steps": STEPS, "authenticated": True},
    )


@router.post("/submit")
async def submit(
    intake: IntakeSubmission,
    background: BackgroundTasks,
    user: CurrentUser = Depends(current_user),
):
    db = anon_client()
    # user_id comes from the verified JWT, never the request body.
    version = 1  # TODO: next version per user
    inserted = db.table("financial_inputs").insert({
        "user_id": user.id,
        "version": version,
        "raw_payload": intake.model_dump(mode="json"),
    }).execute()
    _input_id = inserted.data[0]["id"]  # TODO: fan out into normalized tables

    job = db.table("report_jobs").insert({
        "user_id": user.id,
        "input_version": version,
        "status": "queued",
    }).execute()
    job_id = job.data[0]["id"]

    background.add_task(generate_report, job_id, user.id, version, intake)
    return RedirectResponse(url=f"/dashboard?job={job_id}", status_code=303)

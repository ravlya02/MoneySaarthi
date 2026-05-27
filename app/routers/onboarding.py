"""Multi-step onboarding form (§A.3 Phase 1, §D.2).

Each step POST validates only its own fields, merges into an onboarding_drafts
row, and redirects to the next step. The final step (risk) assembles the full
IntakeSubmission from the draft, writes financial_inputs + normalized tables,
enqueues the report job, and redirects to the dashboard.

Partial state is persisted server-side in onboarding_drafts so a refresh or
dropped connection never loses a half-entered household sheet.
"""

from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.db.supabase_client import anon_client
from app.dependencies import CurrentUser, current_user, optional_user
from app.models.intake import IntakeSubmission
from app.models.onboarding import STEP_MODELS
from app.routers.templates import templates
from app.worker.jobs import generate_report

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

STEPS = [
    "demographics", "income", "expenses", "loans",
    "investments", "insurance", "goals", "risk",
]

# ── Step navigation helpers ──────────────────────────────────────────────────

def _next_step(step: str) -> str | None:
    idx = STEPS.index(step)
    return STEPS[idx + 1] if idx < len(STEPS) - 1 else None


def _prev_step(step: str) -> str | None:
    idx = STEPS.index(step)
    return STEPS[idx - 1] if idx > 0 else None


# ── Multi-row form field parser ──────────────────────────────────────────────

def _parse_indexed(form_data, prefix: str) -> list[dict]:
    """Parse indexed HTML form fields into a list of dicts.

    HTML forms encode multi-row data as prefix[N][field] keys, e.g.:
      incomes[0][earner], incomes[0][monthly_amount], incomes[1][earner]

    Returns a list of dicts in index order, skipping rows where every
    value is blank (handles trailing empty rows added by "Add row" JS).
    """
    rows: dict[int, dict] = {}
    prefix_bracket = f"{prefix}["
    for key, value in form_data.multi_items():
        if not key.startswith(prefix_bracket):
            continue
        rest = key[len(prefix_bracket):]   # e.g. "0][earner]"
        bracket = rest.find("]")
        if bracket == -1:
            continue
        try:
            idx = int(rest[:bracket])
        except ValueError:
            continue
        # rest[bracket] is "]", rest[bracket+1:] is "[field]"
        tail = rest[bracket + 1:]          # e.g. "[earner]"
        if not tail.startswith("[") or not tail.endswith("]"):
            continue
        field = tail[1:-1]                 # strip surrounding brackets
        rows.setdefault(idx, {})[field] = value

    result = []
    for _, row in sorted(rows.items()):
        # Skip entirely-blank rows (user clicked Add row but left it empty)
        if any(v.strip() for v in row.values() if isinstance(v, str)):
            result.append(row)
    return result


def _parse_step_form(step: str, form_data) -> dict:
    """Extract a raw dict from form_data appropriate for the given step model."""
    if step == "demographics":
        return {"members": _parse_indexed(form_data, "members")}
    if step == "income":
        return {"incomes": _parse_indexed(form_data, "incomes")}
    if step == "expenses":
        return {"expenses": _parse_indexed(form_data, "expenses")}
    if step == "loans":
        return {"liabilities": _parse_indexed(form_data, "liabilities")}
    if step == "investments":
        return {"holdings": _parse_indexed(form_data, "holdings")}
    if step == "insurance":
        return {"insurance": _parse_indexed(form_data, "insurance")}
    if step == "goals":
        return {"goals": _parse_indexed(form_data, "goals")}
    if step == "risk":
        return {"risk_appetite": form_data.get("risk_appetite", "")}
    return {}


# ── Draft persistence helpers ────────────────────────────────────────────────

def _load_draft(db, user_id: str) -> dict:
    """Read the user's onboarding draft from the DB. Returns {} if absent."""
    result = (
        db.table("onboarding_drafts")
        .select("draft")
        .eq("user_id", user_id)
        .execute()
    )
    if result.data:
        return result.data[0]["draft"] or {}
    return {}


def _upsert_draft(db, user_id: str, step: str, step_data: dict) -> None:
    """Merge step_data into the existing draft (preserving prior steps)."""
    current = _load_draft(db, user_id)
    current[step] = step_data
    db.table("onboarding_drafts").upsert(
        {"user_id": user_id, "draft": current},
        on_conflict="user_id",
    ).execute()


def _delete_draft(db, user_id: str) -> None:
    """Delete the draft after a successful final submit."""
    db.table("onboarding_drafts").delete().eq("user_id", user_id).execute()


# ── Submission helpers ───────────────────────────────────────────────────────

def _next_version(db, user_id: str) -> int:
    """Auto-increment: max(version) + 1 for the user, default 1."""
    result = (
        db.table("financial_inputs")
        .select("version")
        .eq("user_id", user_id)
        .order("version", desc=True)
        .limit(1)
        .execute()
    )
    if result.data:
        return result.data[0]["version"] + 1
    return 1


def _fan_out(db, input_id: str, user_id: str, intake: IntakeSubmission) -> None:
    """Insert rows into all 6 normalized tables.

    All money fields use str(Decimal) so PostgreSQL numeric columns receive
    exact string representations — no float rounding. (§E.2)
    """
    if intake.incomes:
        db.table("income_sources").insert([
            {
                "input_id": input_id, "user_id": user_id,
                "earner": i.earner, "source_type": i.source_type,
                "monthly_amount": str(i.monthly_amount),
            }
            for i in intake.incomes
        ]).execute()

    if intake.expenses:
        db.table("expenses").insert([
            {
                "input_id": input_id, "user_id": user_id,
                "category": e.category,
                "monthly_amount": str(e.monthly_amount),
            }
            for e in intake.expenses
        ]).execute()

    if intake.liabilities:
        db.table("liabilities").insert([
            {
                "input_id": input_id, "user_id": user_id,
                "loan_type": l.loan_type, "owner": l.owner,
                "emi": str(l.emi),
                "pending_amount": str(l.pending_amount),
                "interest_rate": str(l.interest_rate) if l.interest_rate is not None else None,
                "duration_months": l.duration_months,
            }
            for l in intake.liabilities
        ]).execute()

    if intake.holdings:
        db.table("holdings").insert([
            {
                "input_id": input_id, "user_id": user_id,
                "asset_class": h.asset_class, "instrument": h.instrument,
                "owner": h.owner,
                "sip_monthly": str(h.sip_monthly),
                "invested_amount": str(h.invested_amount),
                "current_corpus": str(h.current_corpus),
                "interest_rate": str(h.interest_rate) if h.interest_rate is not None else None,
            }
            for h in intake.holdings
        ]).execute()

    if intake.insurance:
        db.table("insurance_policies").insert([
            {
                "input_id": input_id, "user_id": user_id,
                "policy_type": p.policy_type,
                "product_name": p.product_name,
                "structure": p.structure,
                "insured": p.insured,
                "premium": str(p.premium) if p.premium is not None else None,
                "premium_frequency": p.premium_frequency,
                "policy_end_date": p.policy_end_date.isoformat() if p.policy_end_date else None,
                "maturity_amount": str(p.maturity_amount) if p.maturity_amount is not None else None,
            }
            for p in intake.insurance
        ]).execute()

    if intake.goals:
        db.table("goals").insert([
            {
                "input_id": input_id, "user_id": user_id,
                "goal_name": g.goal_name,
                "horizon_type": g.horizon_type,
                "duration_years": str(g.duration_years) if g.duration_years is not None else None,
                "amount_required_today": str(g.amount_required_today),
            }
            for g in intake.goals
        ]).execute()


async def _do_submit(
    db,
    background: BackgroundTasks,
    user_id: str,
    intake: IntakeSubmission,
) -> RedirectResponse:
    """Core submit logic: insert financial_inputs, fan out, enqueue job, delete draft."""
    version = _next_version(db, user_id)
    inserted = db.table("financial_inputs").insert({
        "user_id": user_id,
        "version": version,
        "raw_payload": intake.model_dump(mode="json"),
    }).execute()
    input_id = inserted.data[0]["id"]

    _fan_out(db, input_id, user_id, intake)

    job = db.table("report_jobs").insert({
        "user_id": user_id,
        "input_version": version,
        "status": "queued",
    }).execute()
    job_id = job.data[0]["id"]

    background.add_task(generate_report, job_id, user_id, version, intake)
    _delete_draft(db, user_id)
    return RedirectResponse(url=f"/dashboard?job={job_id}", status_code=303)


def _assemble_intake(draft: dict) -> IntakeSubmission:
    """Build a full IntakeSubmission from the accumulated draft dict.

    Raises ValidationError if required fields are missing (e.g. risk_appetite).
    """
    return IntakeSubmission(
        risk_appetite=draft.get("risk", {}).get("risk_appetite"),
        members=draft.get("demographics", {}).get("members", []),
        incomes=draft.get("income", {}).get("incomes", []),
        expenses=draft.get("expenses", {}).get("expenses", []),
        liabilities=draft.get("loans", {}).get("liabilities", []),
        holdings=draft.get("investments", {}).get("holdings", []),
        insurance=draft.get("insurance", {}).get("insurance", []),
        goals=draft.get("goals", {}).get("goals", []),
    )


def _cross_field_warnings(intake: IntakeSubmission) -> list[str]:
    """Return a list of non-blocking advisory warnings for the user.

    These flag data quality issues without preventing submission.
    """
    warnings: list[str] = []
    total_income = sum(i.monthly_amount for i in intake.incomes)
    total_emi = sum(l.emi for l in intake.liabilities)
    if total_income > 0 and total_emi > total_income * Decimal("0.80"):
        warnings.append(
            f"Total EMI (₹{total_emi:,.0f}/mo) exceeds 80% of total monthly income "
            f"(₹{total_income:,.0f}/mo). Consider reviewing your loan obligations."
        )
    for h in intake.holdings:
        if h.current_corpus < h.invested_amount:
            warnings.append(
                f"Holding '{h.instrument}': current corpus (₹{h.current_corpus:,.0f}) "
                f"is less than invested amount (₹{h.invested_amount:,.0f})."
            )
    for p in intake.insurance:
        if p.structure == "Term" and p.maturity_amount and p.maturity_amount > 0:
            name = p.product_name or p.policy_type
            warnings.append(
                f"Policy '{name}': Term policies typically have no maturity amount. "
                f"Please verify."
            )
    return warnings


def _extract_errors(exc: Exception) -> list[str]:
    """Flatten a ValidationError (or any Exception) into human-readable strings."""
    if isinstance(exc, ValidationError):
        return [
            f"{' → '.join(str(loc) for loc in e['loc'])}: {e['msg']}"
            for e in exc.errors()
        ]
    return [str(exc)]


def _template_context(
    step: str,
    draft: dict,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict:
    """Build the common template context dict for any onboarding step."""
    idx = STEPS.index(step)
    return {
        "step": step,
        "step_label": step.capitalize(),
        "step_index": idx + 1,          # 1-based for "Step N of 8" display
        "total_steps": len(STEPS),
        "steps": STEPS,
        "prev_step": _prev_step(step),
        "next_step": _next_step(step),
        "draft": draft,
        "errors": errors or [],
        "warnings": warnings or [],
        "authenticated": True,
    }


# ── Routes ───────────────────────────────────────────────────────────────────
# IMPORTANT: POST /submit must be declared before POST /{step} so the fixed
# path wins over the parameterised route when FastAPI resolves order.


@router.get("/{step}", response_class=HTMLResponse)
async def step_page(
    step: str,
    request: Request,
    settings: Settings = Depends(get_settings),
):
    user = optional_user(request, settings)
    if user is None:
        return RedirectResponse(f"/login?next=/onboarding/{step}", status_code=302)
    if step not in STEPS:
        return RedirectResponse("/onboarding/demographics", status_code=302)

    token = request.cookies.get("access_token", "")
    db = anon_client()
    if token:
        try:
            db.auth.set_session(access_token=token, refresh_token="")
        except Exception:
            pass  # session set is best-effort; RLS applies in production

    draft = _load_draft(db, user.id)
    return templates.TemplateResponse(
        request=request,
        name=f"onboarding/{step}.html",
        context=_template_context(step, draft),
    )


@router.post("/submit")
async def submit(
    intake: IntakeSubmission,
    background: BackgroundTasks,
    user: CurrentUser = Depends(current_user),
):
    """JSON body endpoint — kept for API / test clients.
    Delegates to _do_submit which now auto-increments version and fans out."""
    db = anon_client()
    return await _do_submit(db, background, user.id, intake)


@router.post("/{step}")
async def step_post(
    step: str,
    request: Request,
    background: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """Validate step form data, merge into draft, advance to next step.

    On the final step (risk), assembles the full IntakeSubmission from the
    accumulated draft and triggers the report generation flow.
    """
    user = optional_user(request, settings)
    if user is None:
        return RedirectResponse(f"/login?next=/onboarding/{step}", status_code=302)
    if step not in STEPS:
        return RedirectResponse("/onboarding/demographics", status_code=302)

    token = request.cookies.get("access_token", "")
    db = anon_client()
    if token:
        try:
            db.auth.set_session(access_token=token, refresh_token="")
        except Exception:
            pass

    form_data = await request.form()
    draft = _load_draft(db, user.id)

    # Validate the current step's fields only
    try:
        raw = _parse_step_form(step, form_data)
        model_cls = STEP_MODELS[step]
        validated = model_cls(**raw)
    except (ValidationError, Exception) as exc:
        errors = _extract_errors(exc)
        return templates.TemplateResponse(
            request=request,
            name=f"onboarding/{step}.html",
            context={**_template_context(step, draft, errors=errors), "form_data": form_data},
            status_code=200,
        )

    # Merge validated step data into draft
    _upsert_draft(db, user.id, step, validated.model_dump(mode="json"))

    # Final step: assemble full IntakeSubmission and submit
    if step == "risk":
        updated_draft = _load_draft(db, user.id)
        try:
            intake = _assemble_intake(updated_draft)
        except ValidationError as exc:
            errors = _extract_errors(exc)
            return templates.TemplateResponse(
                request=request,
                name="onboarding/risk.html",
                context=_template_context("risk", updated_draft, errors=errors),
                status_code=200,
            )
        # Cross-field warnings are advisory — do not block submission
        _cross_field_warnings(intake)
        return await _do_submit(db, background, user.id, intake)

    next_s = _next_step(step)
    return RedirectResponse(f"/onboarding/{next_s}", status_code=302)

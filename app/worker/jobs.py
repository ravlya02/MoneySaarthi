"""Background report generation (§A.3 Phase 2). Runs the deterministic engine
first, then AI enrichment. Writes reports via the service_role client (bypasses
RLS). A failed AI call degrades to 'partial', never a 500 on submit."""

from app.ai.orchestrator import enrich_and_synthesize
from app.config import get_settings
from app.db.supabase_client import service_client
from app.engine.runner import run_engine
from app.models.intake import IntakeSubmission


async def generate_report(job_id: str, user_id: str, input_version: int, intake: IntakeSubmission) -> None:
    db = service_client()
    settings = get_settings()
    db.table("report_jobs").update({"status": "running"}).eq("id", job_id).execute()

    try:
        # 1. Deterministic engine — always available, never depends on Gemini.
        engine_output = run_engine(intake, settings.assessment_year)

        # 2. AI enrichment (degrade to partial on failure).
        narrative = None
        try:
            narrative = await enrich_and_synthesize(engine_output)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            db.table("report_jobs").update({"error_detail": f"AI partial: {exc}"}).eq("id", job_id).execute()

        # 3. Persist engine numbers + (optional) narrative.
        _write_reports(db, user_id, input_version, engine_output, narrative)
        db.table("report_jobs").update({"status": "complete"}).eq("id", job_id).execute()
    except Exception as exc:  # noqa: BLE001
        db.table("report_jobs").update({"status": "failed", "error_detail": str(exc)}).eq("id", job_id).execute()
        raise


def _write_reports(db, user_id, input_version, engine_output, narrative) -> None:
    db.table("tax_reports").insert({
        "user_id": user_id,
        "input_version": input_version,
        "assessment_year": engine_output.tax.assessment_year,
        "old_regime_tax": str(engine_output.tax.old_regime_tax),
        "new_regime_tax": str(engine_output.tax.new_regime_tax),
        "recommended_regime": engine_output.tax.recommended_regime,
        "breakdown": engine_output.tax.breakdown,
        "ai_narrative": narrative.summary if narrative else None,
        "ai_action_items": [a.model_dump() for a in narrative.rebalancing_actions] if narrative else None,
    }).execute()

    db.table("investment_plans").insert({
        "user_id": user_id,
        "input_version": input_version,
        "target_equity_pct": str(engine_output.target_allocation.equity),
        "target_debt_pct": str(engine_output.target_allocation.debt),
        "target_realestate_pct": str(engine_output.target_allocation.realestate),
        "target_metals_pct": str(engine_output.target_allocation.metals),
        "plan_detail": {"goal_funding": [g.model_dump(mode="json") for g in engine_output.goal_funding]},
    }).execute()

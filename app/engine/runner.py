"""Top-level deterministic engine entry point. Runs BEFORE any AI call and
produces the authoritative EngineOutput ([VERIFIED FACTS])."""

from decimal import Decimal

from app.engine.allocation import current_allocation, target_allocation
from app.engine.goals import evaluate_goal
from app.engine.tax.compute import compute_tax
from app.models.intake import IntakeSubmission
from app.models.reports import EngineOutput


def run_engine(intake: IntakeSubmission, assessment_year: str) -> EngineOutput:
    gross_income = sum((i.monthly_amount for i in intake.incomes), Decimal(0)) * 12

    return EngineOutput(
        tax=compute_tax(gross_income, assessment_year),
        current_allocation=current_allocation(intake.holdings),
        target_allocation=target_allocation(intake.risk_appetite),
        goal_funding=[evaluate_goal(g) for g in intake.goals],
    )

"""Deterministic goal-funding math: inflate present cost to future value and
compute the monthly SIP required to reach each goal. No LLM involved."""

from decimal import Decimal

from app.models.intake import Goal
from app.models.reports import GoalFunding

DEFAULT_INFLATION = Decimal("0.06")
DEFAULT_EXPECTED_RETURN = Decimal("0.11")


def future_value(present: Decimal, years: Decimal, rate: Decimal = DEFAULT_INFLATION) -> Decimal:
    return (present * (Decimal(1) + rate) ** int(years)).quantize(Decimal("0.01"))


def required_sip(target_fv: Decimal, years: Decimal, annual_return: Decimal = DEFAULT_EXPECTED_RETURN) -> Decimal:
    months = int(years) * 12
    if months == 0:
        return target_fv
    r = annual_return / 12
    factor = ((Decimal(1) + r) ** months - Decimal(1)) / r
    return (target_fv / factor).quantize(Decimal("0.01"))


def evaluate_goal(goal: Goal) -> GoalFunding:
    years = goal.duration_years or Decimal(1)
    fv = future_value(goal.amount_required_today, years)
    return GoalFunding(
        goal_name=goal.goal_name,
        status="shortfall",  # TODO: compare against actual SIP capacity
        future_value_required=fv,
        suggested_monthly_sip=required_sip(fv, years),
    )

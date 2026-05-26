"""Output models. All monetary fields are Decimal and originate from the
deterministic engine — never from the LLM (§E.2)."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class Allocation(BaseModel):
    equity: Decimal
    debt: Decimal
    realestate: Decimal
    metals: Decimal
    cash: Decimal


class TaxResult(BaseModel):
    assessment_year: str
    old_regime_tax: Decimal
    new_regime_tax: Decimal
    recommended_regime: Literal["Old", "New"]
    breakdown: dict  # slab-wise, deductions, surcharge, cess


class GoalFunding(BaseModel):
    goal_name: str
    status: Literal["on-track", "shortfall", "surplus"]
    future_value_required: Decimal
    suggested_monthly_sip: Decimal


class EngineOutput(BaseModel):
    """Everything the deterministic engine produces. This is the authoritative
    set of [VERIFIED FACTS] handed to the AI orchestrator."""

    tax: TaxResult
    current_allocation: Allocation
    target_allocation: Allocation
    goal_funding: list[GoalFunding]


class ActionItem(BaseModel):
    action: str
    instrument: str | None = None
    rationale: str
    source: str | None = None


class AINarrative(BaseModel):
    """Strict schema Gemini must return (§C.3). Contains NO authoritative
    numbers — only prose and action items validated against EngineOutput."""

    summary: str
    tax_explanation: str
    regime_recommendation: str
    rebalancing_actions: list[ActionItem] = []
    goal_action_items: list[dict] = []
    disclaimers: list[str] = []

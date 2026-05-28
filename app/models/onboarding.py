"""Per-step Pydantic models for the multi-step onboarding form.

These are intentionally lighter than IntakeSubmission — each validates only
the fields captured at that step so partial saves never fail on missing
later-step data (§A.3 Phase 1, §D.2)."""

from typing import Literal

from pydantic import BaseModel

from app.models.intake import (
    Goal,
    Holding,
    HouseholdMember,
    IncomeSource,
    InsurancePolicy,
    Liability,
    Expense,
)


class DemographicsStep(BaseModel):
    members: list[HouseholdMember] = []


class IncomeStep(BaseModel):
    incomes: list[IncomeSource] = []


class ExpensesStep(BaseModel):
    expenses: list[Expense] = []


class LoansStep(BaseModel):
    liabilities: list[Liability] = []


class InvestmentsStep(BaseModel):
    holdings: list[Holding] = []


class InsuranceStep(BaseModel):
    insurance: list[InsurancePolicy] = []


class GoalsStep(BaseModel):
    goals: list[Goal] = []


class RiskStep(BaseModel):
    risk_appetite: Literal["Conservative", "Moderate", "Aggressive"]


# Map step name → model class; used by the POST handler for dispatch.
STEP_MODELS: dict[str, type[BaseModel]] = {
    "demographics": DemographicsStep,
    "income":       IncomeStep,
    "expenses":     ExpensesStep,
    "loans":        LoansStep,
    "investments":  InvestmentsStep,
    "insurance":    InsuranceStep,
    "goals":        GoalsStep,
    "risk":         RiskStep,
}

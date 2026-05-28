"""Validated intake models. Money is always Decimal, never float (§E.2).
Invalid figures are rejected back to the form, never coerced."""

from decimal import Decimal
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, NonNegativeInt

Money = Decimal  # use condecimal/validators per field for ranges


class HouseholdMember(BaseModel):
    member_role: Literal["Sir", "Mam", "Child", "Parent", "Other"]
    display_name: str | None = None
    age: Decimal | None = Field(default=None, ge=0, le=120)
    studies_in_class: str | None = None
    financially_dependent: bool = False


class IncomeSource(BaseModel):
    earner: Literal["Sir", "Mam", "Father", "Mother"]
    source_type: Literal["Salary", "Business", "Rental", "FD Interest", "Other"]
    monthly_amount: Decimal = Field(ge=0)


class Expense(BaseModel):
    category: str
    monthly_amount: Decimal = Field(ge=0)


class Liability(BaseModel):
    loan_type: str
    owner: Literal["Sir", "Mam", "Joint", "Father", "Mother"] | None = None
    emi: Decimal = Field(default=Decimal(0), ge=0)
    pending_amount: Decimal = Field(default=Decimal(0), ge=0)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=30)
    duration_months: NonNegativeInt | None = None


class Holding(BaseModel):
    asset_class: Literal["Equity", "Debt", "RealEstate", "Metals", "Cash"]
    instrument: str
    owner: Literal["Sir", "Mam", "Father", "Mother"] | None = None
    sip_monthly: Decimal = Field(default=Decimal(0), ge=0)
    invested_amount: Decimal = Field(default=Decimal(0), ge=0)
    current_corpus: Decimal = Field(default=Decimal(0), ge=0)
    interest_rate: Decimal | None = Field(default=None, ge=0, le=30)


class InsurancePolicy(BaseModel):
    policy_type: Literal["Life", "Health", "Corporate Life", "Corporate Health"]
    product_name: str | None = None
    structure: Literal["Term", "ULIP", "Endowment"] | None = None
    insured: Literal["Sir", "Mam", "Father", "Mother", "Family", "Family and Parents"] | None = None
    premium: Decimal | None = Field(default=None, ge=0)
    premium_frequency: Literal["Monthly", "Quarterly", "Half-Yearly", "Annually"] | None = None
    policy_end_date: date | None = None
    maturity_amount: Decimal | None = Field(default=None, ge=0)


class Goal(BaseModel):
    goal_name: str
    horizon_type: Literal["Short", "Long", "Retirement"] | None = None
    duration_years: Decimal | None = Field(default=None, ge=0)
    amount_required_today: Decimal = Field(ge=0)


class IntakeSubmission(BaseModel):
    """Full validated form snapshot. Persisted verbatim to financial_inputs."""

    risk_appetite: Literal["Conservative", "Moderate", "Aggressive"]
    members: list[HouseholdMember] = []
    incomes: list[IncomeSource] = []
    expenses: list[Expense] = []
    liabilities: list[Liability] = []
    holdings: list[Holding] = []
    insurance: list[InsurancePolicy] = []
    goals: list[Goal] = []

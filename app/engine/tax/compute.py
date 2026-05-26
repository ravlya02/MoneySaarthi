"""Deterministic tax computation — old vs new regime. No LLM involved (§E.2)."""

from decimal import Decimal

from app.engine.tax.rules import rules_for
from app.models.reports import TaxResult


def _slab_tax(taxable: Decimal, slabs: list[tuple[Decimal | None, Decimal]]) -> Decimal:
    tax = Decimal(0)
    lower = Decimal(0)
    for upper, rate in slabs:
        if upper is None:
            tax += (taxable - lower).max(Decimal(0)) * rate
            break
        band = (min(taxable, upper) - lower).max(Decimal(0))
        tax += band * rate
        if taxable <= upper:
            break
        lower = upper
    return tax


def compute_new_regime(gross_income: Decimal, assessment_year: str) -> Decimal:
    r = rules_for(assessment_year)
    taxable = (gross_income - r["standard_deduction_new"]).max(Decimal(0))
    tax = _slab_tax(taxable, r["new_regime_slabs"])
    if taxable <= r["rebate_87a_limit_new"]:  # 87A rebate
        tax = Decimal(0)
    return (tax * (Decimal(1) + r["cess_rate"])).quantize(Decimal("0.01"))


def compute_old_regime(
    gross_income: Decimal, deductions: Decimal, assessment_year: str
) -> Decimal:
    # TODO: implement old-regime slabs + 80C/80D/HRA handling.
    raise NotImplementedError


def compute_tax(gross_income: Decimal, assessment_year: str) -> TaxResult:
    new_tax = compute_new_regime(gross_income, assessment_year)
    # old_tax = compute_old_regime(...)  # once implemented
    old_tax = new_tax  # placeholder until old regime is built
    recommended = "New" if new_tax <= old_tax else "Old"
    return TaxResult(
        assessment_year=assessment_year,
        old_regime_tax=old_tax,
        new_regime_tax=new_tax,
        recommended_regime=recommended,
        breakdown={"note": "old regime not yet implemented"},
    )

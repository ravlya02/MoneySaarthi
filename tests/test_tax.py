from decimal import Decimal

from app.engine.tax.compute import compute_new_regime

AY = "AY 2026-27"


def test_income_under_rebate_limit_is_tax_free():
    # Taxable after 75k std deduction <= 12L → 87A rebate zeroes the tax.
    assert compute_new_regime(Decimal("1275000"), AY) == Decimal("0.00")


def test_high_income_pays_tax_with_cess():
    tax = compute_new_regime(Decimal("3300000"), AY)
    assert tax > 0

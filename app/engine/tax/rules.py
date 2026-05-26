"""Versioned, unit-tested tax rules keyed by assessment year (§E.2).

These rules NEVER live in a prompt. A future-year change is a data change here,
not a code rewrite. All amounts are Decimal.
"""

from decimal import Decimal

# New regime slabs, AY 2026-27 (FY 2025-26). Each tuple: (upper_bound, rate).
# None upper bound means "and above".
NEW_REGIME_SLABS_AY_2026_27: list[tuple[Decimal | None, Decimal]] = [
    (Decimal("400000"), Decimal("0.00")),
    (Decimal("800000"), Decimal("0.05")),
    (Decimal("1200000"), Decimal("0.10")),
    (Decimal("1600000"), Decimal("0.15")),
    (Decimal("2000000"), Decimal("0.20")),
    (Decimal("2400000"), Decimal("0.25")),
    (None, Decimal("0.30")),
]

STANDARD_DEDUCTION_NEW = Decimal("75000")
SECTION_87A_REBATE_LIMIT_NEW = Decimal("1200000")  # income up to 12L effectively tax-free
CESS_RATE = Decimal("0.04")  # health & education cess

# Old regime slabs and deduction caps live here too once implemented.

RULES_BY_AY: dict[str, dict] = {
    "AY 2026-27": {
        "new_regime_slabs": NEW_REGIME_SLABS_AY_2026_27,
        "standard_deduction_new": STANDARD_DEDUCTION_NEW,
        "rebate_87a_limit_new": SECTION_87A_REBATE_LIMIT_NEW,
        "cess_rate": CESS_RATE,
    },
}


def rules_for(assessment_year: str) -> dict:
    if assessment_year not in RULES_BY_AY:
        raise KeyError(f"No tax rules registered for {assessment_year}")
    return RULES_BY_AY[assessment_year]

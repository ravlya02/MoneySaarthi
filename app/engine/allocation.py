"""Deterministic asset-allocation math: current weights, target weights by risk
profile/horizon, and current-vs-target gaps. No LLM involved."""

from decimal import Decimal

from app.models.intake import Holding
from app.models.reports import Allocation

# Target allocations by risk appetite (Equity/Debt/RealEstate/Metals/Cash).
TARGETS: dict[str, Allocation] = {
    "Conservative": Allocation(equity=Decimal(30), debt=Decimal(50), realestate=Decimal(10), metals=Decimal(5), cash=Decimal(5)),
    "Moderate": Allocation(equity=Decimal(60), debt=Decimal(25), realestate=Decimal(10), metals=Decimal(5), cash=Decimal(0)),
    "Aggressive": Allocation(equity=Decimal(75), debt=Decimal(10), realestate=Decimal(10), metals=Decimal(5), cash=Decimal(0)),
}


def current_allocation(holdings: list[Holding]) -> Allocation:
    buckets = {"Equity": Decimal(0), "Debt": Decimal(0), "RealEstate": Decimal(0), "Metals": Decimal(0), "Cash": Decimal(0)}
    for h in holdings:
        buckets[h.asset_class] += h.current_corpus
    total = sum(buckets.values()) or Decimal(1)
    pct = {k: (v / total * 100).quantize(Decimal("0.01")) for k, v in buckets.items()}
    return Allocation(equity=pct["Equity"], debt=pct["Debt"], realestate=pct["RealEstate"], metals=pct["Metals"], cash=pct["Cash"])


def target_allocation(risk_appetite: str) -> Allocation:
    return TARGETS[risk_appetite]

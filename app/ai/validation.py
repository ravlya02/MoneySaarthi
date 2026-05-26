"""Output validation — the concrete anti-hallucination mechanism (§E.2).

After Gemini responds, scan the narrative for rupee figures and assert they
match the engine's verified facts. Any number Gemini introduced that isn't in
EngineOutput is rejected/stripped before the report reaches the dashboard.
"""

import re
from decimal import Decimal

from app.models.reports import AINarrative, EngineOutput

_RUPEE = re.compile(r"₹\s?([\d,]+(?:\.\d+)?)")


def _figures(text: str) -> set[Decimal]:
    out = set()
    for m in _RUPEE.finditer(text):
        try:
            out.add(Decimal(m.group(1).replace(",", "")))
        except Exception:
            continue
    return out


def verified_numbers(engine: EngineOutput) -> set[Decimal]:
    nums = {engine.tax.old_regime_tax, engine.tax.new_regime_tax}
    for g in engine.goal_funding:
        nums.add(g.future_value_required)
        nums.add(g.suggested_monthly_sip)
    return {Decimal(n) for n in nums}


def assert_no_hallucinated_numbers(narrative: AINarrative, engine: EngineOutput) -> list[Decimal]:
    """Return any rupee figures in the narrative not present in EngineOutput.
    A non-empty result means the narrative must be rejected or stripped."""
    allowed = verified_numbers(engine)
    blob = " ".join([narrative.summary, narrative.tax_explanation, narrative.regime_recommendation])
    return [n for n in _figures(blob) if n not in allowed]

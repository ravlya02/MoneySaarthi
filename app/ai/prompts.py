"""Sectioned prompt builder (§C.3). Numbers are quarantined in [VERIFIED FACTS]
and marked immutable; Gemini writes narrative only and must refuse to state any
number not present there."""

from app.models.reports import Passage
from app.ai.web_search import MarketFact
from app.models.reports import EngineOutput

SYSTEM = """You are a financial-advisory writing assistant for the Indian market.
You explain and recommend; you NEVER recalculate or invent monetary figures.
All rupee amounts, tax numbers, and allocation percentages in [VERIFIED FACTS]
are computed and final. If a number is not in [VERIFIED FACTS], say it is not
available — do not estimate it. Cite tax rules only from [KNOWLEDGE BASE].
Output strictly in the JSON schema given in [OUTPUT FORMAT]."""

OUTPUT_FORMAT = """{ "summary": str, "tax_explanation": str, "regime_recommendation": str,
  "rebalancing_actions": [ {action, instrument, rationale, source?} ],
  "goal_action_items": [ {goal, status, suggested_monthly_sip} ],
  "disclaimers": [str] }"""


def build_prompt(engine: EngineOutput, market: list[MarketFact], passages: list[Passage]) -> str:
    facts = [
        f"- Tax: Old regime ₹{engine.tax.old_regime_tax} ; New regime ₹{engine.tax.new_regime_tax} ; Recommended: {engine.tax.recommended_regime}",
        f"- Current allocation: Equity {engine.current_allocation.equity}% / Debt {engine.current_allocation.debt}% / RealEstate {engine.current_allocation.realestate}% / Metals {engine.current_allocation.metals}% / Cash {engine.current_allocation.cash}%",
        f"- Target allocation: Equity {engine.target_allocation.equity} / Debt {engine.target_allocation.debt} / RealEstate {engine.target_allocation.realestate} / Metals {engine.target_allocation.metals}",
    ]
    facts += [f"- Goal {g.goal_name}: {g.status}, FV ₹{g.future_value_required}, SIP ₹{g.suggested_monthly_sip}" for g in engine.goal_funding]

    market_lines = [f"- {m.label}: {m.value} [{m.source_url}, fetched {m.fetched_at}]" for m in market] or ["- (live market data unavailable)"]
    kb_lines = [f"- {p.doc_title} §{p.section}: {p.text}" for p in passages]

    return "\n\n".join([
        f"[SYSTEM]\n{SYSTEM}",
        "[VERIFIED FACTS]  (deterministic engine — authoritative, do not alter)\n" + "\n".join(facts),
        "[LIVE MARKET DATA]  (web-search agent — current, cite sources)\n" + "\n".join(market_lines),
        "[KNOWLEDGE BASE]  (RAG from Qdrant — authoritative for RULES only)\n" + "\n".join(kb_lines),
        f"[OUTPUT FORMAT]\n{OUTPUT_FORMAT}",
    ])

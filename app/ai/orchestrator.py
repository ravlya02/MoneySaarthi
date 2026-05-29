"""AI Orchestrator (§A, §C). Gathers web + RAG context, assembles the prompt,
calls Gemini, and validates output. NEVER originates financial numbers."""

from app.ai import gemini, rag, validation, web_search
from app.ai.prompts import build_prompt
from app.ai.web_search import MAX_TOOL_CALLS
from app.models.reports import AINarrative, EngineOutput


def _derive_planned_searches(engine: EngineOutput) -> list[dict]:
    """Map allocation gaps to a shortlist of tool calls, capped at MAX_TOOL_CALLS."""
    searches: list[dict] = []
    cur = engine.current_allocation
    tgt = engine.target_allocation

    if tgt.equity - cur.equity > 5:
        searches.append({
            "tool": "search_top_funds",
            "params": {"category": "LargeCap", "horizon_years": 5},
        })

    if tgt.debt - cur.debt > 5:
        searches.append({
            "tool": "get_fixed_income_rates",
            "params": {"instrument": "FD"},
        })
        searches.append({
            "tool": "get_fixed_income_rates",
            "params": {"instrument": "PPF"},
        })

    return searches[:MAX_TOOL_CALLS]


async def enrich_and_synthesize(engine: EngineOutput) -> AINarrative:
    # 1. Pre-derive searches from engine allocation gaps, gather live market data (bounded).
    planned = _derive_planned_searches(engine)
    market = await web_search.gather_market_data(planned)

    # 2. Retrieve grounding passages (tax filtered by assessment year).
    tax_passages = rag.retrieve_tax_passages("regime comparison and deductions", engine.tax.assessment_year)
    strategy_passages = rag.retrieve_strategy_passages("asset allocation and rebalancing")

    # 3. Assemble prompt + synthesize.
    prompt = build_prompt(engine, market, tax_passages + strategy_passages)
    narrative = await gemini.synthesize(prompt)

    # 4. Anti-hallucination check (§E.2).
    stray = validation.assert_no_hallucinated_numbers(narrative, engine)
    if stray:
        raise ValueError(f"Gemini introduced unverified figures: {stray}")

    return narrative

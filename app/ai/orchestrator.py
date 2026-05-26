"""AI Orchestrator (§A, §C). Gathers web + RAG context, assembles the prompt,
calls Gemini, and validates output. NEVER originates financial numbers."""

from app.ai import gemini, rag, validation, web_search
from app.ai.prompts import build_prompt
from app.models.reports import AINarrative, EngineOutput


async def enrich_and_synthesize(engine: EngineOutput) -> AINarrative:
    # 1. Pre-derive searches from engine gaps, gather live market data (bounded).
    planned: list[dict] = []  # TODO: derive from current-vs-target gaps
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

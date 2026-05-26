"""Web-Search Agent (§C.1). Gemini function-calling loop, bounded by hard
limits. Results are scraped to structured facts before reaching Gemini."""

from dataclasses import dataclass

MAX_TOOL_CALLS = 5
PER_CALL_TIMEOUT_S = 8
GLOBAL_BUDGET_S = 25

# Tool declarations exposed to Gemini.
TOOLS = [
    {
        "name": "search_top_funds",
        "description": "Find current top-performing mutual funds for a category/horizon.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["LargeCap", "MidCap", "SmallCap", "FlexiCap", "Index", "ELSS", "Debt", "Hybrid"]},
                "horizon_years": {"type": "integer"},
                "risk": {"type": "string", "enum": ["Conservative", "Moderate", "Aggressive"]},
            },
            "required": ["category"],
        },
    },
    {
        "name": "get_fixed_income_rates",
        "description": "Current FD / RD / PPF / Sukanya / NPS / SCSS rates.",
        "parameters": {"type": "object", "properties": {"instrument": {"type": "string"}}, "required": ["instrument"]},
    },
]


@dataclass
class MarketFact:
    label: str
    value: str
    source_url: str
    fetched_at: str


def search_top_funds(category: str, horizon_years: int | None = None, risk: str | None = None) -> list[MarketFact]:
    """Call the configured provider (Tavily/Brave/SerpAPI), scrape to structured
    facts, cache by (tool, params, date). TODO: implement provider call."""
    raise NotImplementedError


def get_fixed_income_rates(instrument: str) -> list[MarketFact]:
    raise NotImplementedError


async def gather_market_data(planned_searches: list[dict]) -> list[MarketFact]:
    """Execute a pre-derived shortlist of searches within the global budget.
    On budget exhaustion, return what was gathered (report notes partial data)."""
    raise NotImplementedError

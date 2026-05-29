"""Tests for the Web-Search Agent (app/ai/web_search.py).

All Tavily calls and Supabase interactions are mocked — no live keys needed.
"""

import asyncio
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.ai.web_search import (
    MAX_TOOL_CALLS,
    _call_tavily,
    _scrape_fund_facts,
    _scrape_rate_facts,
    gather_market_data,
    get_fixed_income_rates,
    search_top_funds,
)
from app.ai.orchestrator import _derive_planned_searches
from app.models.reports import (
    Allocation,
    EngineOutput,
    GoalFunding,
    MarketFact,
    TaxResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FUND_RESULT = {
    "url": "https://valueresearchonline.com/funds/large-cap/mirae-asset",
    "title": "Mirae Asset Large Cap Fund - Direct Plan - Growth",
    "content": "5Y CAGR: 18.4% | 3Y: 14.2% | ER: 0.52% | AUM: ₹32,500 Cr",
    "score": 0.85,
}

RATE_RESULT = {
    "url": "https://nsiindia.gov.in/interest-rates",
    "title": "PPF Interest Rate 2025 — NSI India",
    "content": "PPF rate: 7.1% per annum. SCSS rate: 8.2%. NSC rate: 7.7%. FD rate: 7.0%.",
    "score": 0.92,
}

LOW_SCORE_RESULT = {
    "url": "https://example.com/garbage",
    "title": "Some irrelevant page",
    "content": "5Y CAGR: 99.9% | ER: 0.01%",
    "score": 0.3,
}


def _make_engine(equity_gap: int = 0, debt_gap: int = 0) -> EngineOutput:
    """Build a minimal EngineOutput with controlled allocation gaps."""
    cur_equity = Decimal(50)
    cur_debt = Decimal(30)
    return EngineOutput(
        tax=TaxResult(
            assessment_year="AY 2026-27",
            old_regime_tax=Decimal("100000"),
            new_regime_tax=Decimal("80000"),
            recommended_regime="New",
            breakdown={},
        ),
        current_allocation=Allocation(
            equity=cur_equity,
            debt=cur_debt,
            realestate=Decimal(10),
            metals=Decimal(5),
            cash=Decimal(5),
        ),
        target_allocation=Allocation(
            equity=cur_equity + equity_gap,
            debt=cur_debt + debt_gap,
            realestate=Decimal(10),
            metals=Decimal(5),
            cash=Decimal(5),
        ),
        goal_funding=[
            GoalFunding(
                goal_name="Retirement",
                status="on-track",
                future_value_required=Decimal("5000000"),
                suggested_monthly_sip=Decimal("25000"),
            )
        ],
    )


# ---------------------------------------------------------------------------
# MarketFact model tests
# ---------------------------------------------------------------------------

def test_market_fact_serialisable():
    fact = MarketFact(
        label="Mirae Asset Large Cap – 5Y CAGR",
        value="18.4%",
        source_url="https://valueresearchonline.com/",
        fetched_at="2026-05-29",
    )
    dumped = fact.model_dump()
    assert dumped["label"] == "Mirae Asset Large Cap – 5Y CAGR"
    assert dumped["value"] == "18.4%"
    schema = MarketFact.model_json_schema()
    assert "label" in schema["properties"]


# ---------------------------------------------------------------------------
# Scraping tests
# ---------------------------------------------------------------------------

def test_scrape_fund_facts_extracts_cagr():
    facts = _scrape_fund_facts([FUND_RESULT], "LargeCap")
    values = [f.value for f in facts]
    assert any("18.4%" in v for v in values), f"Expected 18.4% in {values}"


def test_scrape_fund_facts_extracts_expense_ratio():
    facts = _scrape_fund_facts([FUND_RESULT], "LargeCap")
    labels = [f.label for f in facts]
    assert any("Expense Ratio" in l for l in labels), f"Expected ER label in {labels}"


def test_scrape_fund_facts_extracts_aum():
    facts = _scrape_fund_facts([FUND_RESULT], "LargeCap")
    labels = [f.label for f in facts]
    assert any("AUM" in l for l in labels), f"Expected AUM label in {labels}"


def test_scrape_fund_facts_skips_low_score():
    facts = _scrape_fund_facts([LOW_SCORE_RESULT], "LargeCap")
    assert facts == [], f"Expected empty list for low-score result, got {facts}"


def test_scrape_fund_facts_source_url_populated():
    facts = _scrape_fund_facts([FUND_RESULT], "LargeCap")
    assert all(f.source_url == FUND_RESULT["url"] for f in facts)


def test_scrape_rate_facts_extracts_ppf():
    facts = _scrape_rate_facts([RATE_RESULT], "PPF")
    values = [f.value for f in facts]
    assert any("7.1%" in v for v in values), f"Expected PPF 7.1% in {values}"


def test_scrape_rate_facts_extracts_scss():
    facts = _scrape_rate_facts([RATE_RESULT], "SCSS")
    values = [f.value for f in facts]
    assert any("8.2%" in v for v in values), f"Expected SCSS 8.2% in {values}"


def test_scrape_rate_facts_skips_low_score():
    facts = _scrape_rate_facts([LOW_SCORE_RESULT], "PPF")
    assert facts == []


# ---------------------------------------------------------------------------
# Cache interaction tests
# ---------------------------------------------------------------------------

def test_cache_hit_skips_tavily():
    cached_facts = [MarketFact(label="X", value="10%", source_url="http://a.com", fetched_at="2026-05-29")]
    with (
        patch("app.ai.web_search._cache_get", return_value=cached_facts) as mock_get,
        patch("app.ai.web_search._call_tavily") as mock_tavily,
    ):
        result = search_top_funds("LargeCap", horizon_years=5)

    assert result == cached_facts
    mock_get.assert_called_once()
    mock_tavily.assert_not_called()


def test_cache_miss_calls_tavily_and_caches():
    with (
        patch("app.ai.web_search._cache_get", return_value=None),
        patch("app.ai.web_search._call_tavily", return_value=[FUND_RESULT]) as mock_tavily,
        patch("app.ai.web_search._cache_set") as mock_set,
    ):
        result = search_top_funds("LargeCap", horizon_years=5)

    mock_tavily.assert_called_once()
    mock_set.assert_called_once()
    assert isinstance(result, list)


def test_fixed_income_cache_hit_skips_tavily():
    cached_facts = [MarketFact(label="PPF rate", value="7.1%", source_url="http://nsi.gov.in", fetched_at="2026-05-29")]
    with (
        patch("app.ai.web_search._cache_get", return_value=cached_facts),
        patch("app.ai.web_search._call_tavily") as mock_tavily,
    ):
        result = get_fixed_income_rates("PPF")

    assert result == cached_facts
    mock_tavily.assert_not_called()


# ---------------------------------------------------------------------------
# gather_market_data — hard bounds tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_gather_market_data_respects_max_calls():
    """With 5 planned searches, only MAX_TOOL_CALLS=3 should be dispatched."""
    call_count = 0

    def fake_search_funds(**kwargs):
        nonlocal call_count
        call_count += 1
        return []

    def fake_rates(**kwargs):
        nonlocal call_count
        call_count += 1
        return []

    planned = [
        {"tool": "search_top_funds", "params": {"category": "LargeCap"}},
        {"tool": "get_fixed_income_rates", "params": {"instrument": "FD"}},
        {"tool": "get_fixed_income_rates", "params": {"instrument": "PPF"}},
        {"tool": "search_top_funds", "params": {"category": "MidCap"}},
        {"tool": "get_fixed_income_rates", "params": {"instrument": "SCSS"}},
    ]

    with (
        patch("app.ai.web_search.search_top_funds", side_effect=fake_search_funds),
        patch("app.ai.web_search.get_fixed_income_rates", side_effect=fake_rates),
    ):
        await gather_market_data(planned)

    assert call_count == MAX_TOOL_CALLS, f"Expected {MAX_TOOL_CALLS} calls, got {call_count}"


@pytest.mark.anyio
async def test_gather_market_data_continues_on_exception():
    """A failed tool call must not abort the remaining searches."""
    good_fact = MarketFact(label="OK", value="7%", source_url="http://x.com", fetched_at="2026-05-29")
    # First call raises; second call returns a fact.
    side_effects = [RuntimeError("network error"), [good_fact]]

    planned = [
        {"tool": "get_fixed_income_rates", "params": {"instrument": "FD"}},
        {"tool": "get_fixed_income_rates", "params": {"instrument": "PPF"}},
    ]

    with patch("app.ai.web_search.get_fixed_income_rates", side_effect=side_effects):
        facts = await gather_market_data(planned)

    # First call fails (not counted), second succeeds → 1 fact in result.
    assert len(facts) == 1


@pytest.mark.anyio
async def test_gather_market_data_returns_empty_on_no_searches():
    facts = await gather_market_data([])
    assert facts == []


# ---------------------------------------------------------------------------
# _derive_planned_searches tests
# ---------------------------------------------------------------------------

def test_derive_planned_searches_equity_gap():
    engine = _make_engine(equity_gap=20, debt_gap=0)
    searches = _derive_planned_searches(engine)
    tools = [s["tool"] for s in searches]
    assert "search_top_funds" in tools


def test_derive_planned_searches_debt_gap():
    engine = _make_engine(equity_gap=0, debt_gap=15)
    searches = _derive_planned_searches(engine)
    instruments = [s["params"].get("instrument") for s in searches if s["tool"] == "get_fixed_income_rates"]
    assert "FD" in instruments
    assert "PPF" in instruments


def test_derive_planned_searches_no_gap():
    engine = _make_engine(equity_gap=2, debt_gap=3)
    searches = _derive_planned_searches(engine)
    assert searches == []


def test_derive_planned_searches_respects_max_calls():
    engine = _make_engine(equity_gap=20, debt_gap=20)
    searches = _derive_planned_searches(engine)
    assert len(searches) <= MAX_TOOL_CALLS


# ---------------------------------------------------------------------------
# Import-without-key test
# ---------------------------------------------------------------------------

def test_web_search_imports_without_api_key():
    """Module must be importable even with an empty WEB_SEARCH_API_KEY."""
    import importlib
    import app.ai.web_search as ws
    importlib.reload(ws)  # confirm re-import succeeds
    assert ws.MAX_TOOL_CALLS == 3

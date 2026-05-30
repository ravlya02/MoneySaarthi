"""Tests for the RAG pipeline (app/ai/rag.py) and ingestion helpers (app/ai/ingest.py).

All Qdrant and Gemini calls are mocked — no live keys needed.
"""

from unittest.mock import MagicMock, call, patch

import pytest

from app.ai.rag import RERANK_TO, TAX_CORPUS, STRATEGY_CORPUS, retrieve_strategy_passages, retrieve_tax_passages
from app.ai.ingest import chunk_text, ensure_collections
from app.models.reports import Passage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_VECTOR = [0.1] * 3072

_TAX_PAYLOAD = {
    "corpus": TAX_CORPUS,
    "doc_title": "Income Tax Act 2025",
    "section": "Section 115BAC",
    "source_url": "",
    "effective_ay": "AY 2026-27",
    "text": "New regime slab: income up to ₹4L taxed at 0%.",
}

_STRATEGY_PAYLOAD = {
    "corpus": STRATEGY_CORPUS,
    "doc_title": "Investment Analysis",
    "section": "Chapter 3",
    "source_url": "",
    "effective_ay": None,
    "text": "Diversify across equity, debt and real estate.",
}


def _make_scored_point(payload: dict, score: float = 0.9) -> MagicMock:
    pt = MagicMock()
    pt.score = score
    pt.payload = payload
    return pt


def _make_scored_points(n: int, payload: dict) -> list[MagicMock]:
    return [_make_scored_point(payload, score=1.0 - i * 0.01) for i in range(n)]


# ---------------------------------------------------------------------------
# Passage model tests
# ---------------------------------------------------------------------------

def test_passage_model_serialisable():
    p = Passage(
        corpus=TAX_CORPUS,
        doc_title="Income Tax Act 2025",
        section="Section 87A",
        source_url="",
        effective_ay="AY 2026-27",
        text="Rebate up to ₹12L income.",
    )
    dumped = p.model_dump()
    assert dumped["corpus"] == TAX_CORPUS
    assert dumped["effective_ay"] == "AY 2026-27"
    schema = Passage.model_json_schema()
    assert "corpus" in schema["properties"]


def test_passage_effective_ay_optional():
    p = Passage(
        corpus=STRATEGY_CORPUS,
        doc_title="Portfolio Mgmt",
        section="ch1",
        source_url="",
        text="Diversify.",
    )
    assert p.effective_ay is None


# ---------------------------------------------------------------------------
# retrieve_tax_passages tests
# ---------------------------------------------------------------------------

@patch("app.ai.rag._qdrant_client")
@patch("app.ai.rag.embed", return_value=_FAKE_VECTOR)
def test_retrieve_tax_uses_ay_filter(mock_embed, mock_client):
    mock_client.return_value.search.return_value = [_make_scored_point(_TAX_PAYLOAD)]
    retrieve_tax_passages("tax slabs", "AY 2026-27")
    call_kwargs = mock_client.return_value.search.call_args
    query_filter = call_kwargs.kwargs.get("query_filter") or call_kwargs.args[2] if len(call_kwargs.args) > 2 else None
    # query_filter is passed as a keyword argument
    assert call_kwargs.kwargs.get("query_filter") is not None


@patch("app.ai.rag._qdrant_client")
@patch("app.ai.rag.embed", return_value=_FAKE_VECTOR)
def test_retrieve_tax_filter_contains_ay(mock_embed, mock_client):
    mock_client.return_value.search.return_value = [_make_scored_point(_TAX_PAYLOAD)]
    retrieve_tax_passages("tax slabs", "AY 2026-27")
    kwargs = mock_client.return_value.search.call_args.kwargs
    # The filter's must conditions should reference effective_ay = AY 2026-27
    filt = kwargs["query_filter"]
    condition = filt.must[0]
    assert condition.key == "effective_ay"
    assert condition.match.value == "AY 2026-27"


@patch("app.ai.rag._qdrant_client")
@patch("app.ai.rag.embed", return_value=_FAKE_VECTOR)
def test_retrieve_tax_reranks_to_rerank_to(mock_embed, mock_client):
    mock_client.return_value.search.return_value = _make_scored_points(20, _TAX_PAYLOAD)
    result = retrieve_tax_passages("slabs", "AY 2026-27")
    assert len(result) <= RERANK_TO


@patch("app.ai.rag._qdrant_client")
@patch("app.ai.rag.embed", return_value=_FAKE_VECTOR)
def test_retrieve_tax_returns_passage_objects(mock_embed, mock_client):
    mock_client.return_value.search.return_value = [_make_scored_point(_TAX_PAYLOAD)]
    result = retrieve_tax_passages("slabs", "AY 2026-27")
    assert all(isinstance(p, Passage) for p in result)
    assert result[0].corpus == TAX_CORPUS


@patch("app.ai.rag._qdrant_client")
@patch("app.ai.rag.embed", return_value=_FAKE_VECTOR)
def test_retrieve_tax_empty_on_exception(mock_embed, mock_client):
    mock_client.return_value.search.side_effect = Exception("connection refused")
    result = retrieve_tax_passages("slabs", "AY 2026-27")
    assert result == []


# ---------------------------------------------------------------------------
# retrieve_strategy_passages tests
# ---------------------------------------------------------------------------

@patch("app.ai.rag._qdrant_client")
@patch("app.ai.rag.embed", return_value=_FAKE_VECTOR)
def test_retrieve_strategy_no_ay_filter(mock_embed, mock_client):
    mock_client.return_value.search.return_value = [_make_scored_point(_STRATEGY_PAYLOAD)]
    retrieve_strategy_passages("asset allocation")
    kwargs = mock_client.return_value.search.call_args.kwargs
    assert kwargs.get("query_filter") is None


@patch("app.ai.rag._qdrant_client")
@patch("app.ai.rag.embed", return_value=_FAKE_VECTOR)
def test_retrieve_strategy_targets_correct_collection(mock_embed, mock_client):
    mock_client.return_value.search.return_value = [_make_scored_point(_STRATEGY_PAYLOAD)]
    retrieve_strategy_passages("rebalancing")
    kwargs = mock_client.return_value.search.call_args.kwargs
    assert kwargs["collection_name"] == STRATEGY_CORPUS


@patch("app.ai.rag._qdrant_client")
@patch("app.ai.rag.embed", return_value=_FAKE_VECTOR)
def test_retrieve_strategy_reranks_to_rerank_to(mock_embed, mock_client):
    mock_client.return_value.search.return_value = _make_scored_points(20, _STRATEGY_PAYLOAD)
    result = retrieve_strategy_passages("allocation")
    assert len(result) <= RERANK_TO


@patch("app.ai.rag._qdrant_client")
@patch("app.ai.rag.embed", return_value=_FAKE_VECTOR)
def test_retrieve_strategy_empty_on_exception(mock_embed, mock_client):
    mock_client.return_value.search.side_effect = Exception("timeout")
    result = retrieve_strategy_passages("allocation")
    assert result == []


# ---------------------------------------------------------------------------
# Import-without-keys test
# ---------------------------------------------------------------------------

def test_rag_imports_without_keys():
    import importlib
    import app.ai.rag as rag_module
    importlib.reload(rag_module)
    assert rag_module.RETRIEVE_K == 20
    assert rag_module.RERANK_TO == 6


# ---------------------------------------------------------------------------
# chunk_text tests
# ---------------------------------------------------------------------------

_SAMPLE_TAX_TEXT = (
    "Section 1 Introduction\nThis act governs taxation.\n\n"
    "Section 2 Definitions\nFor the purposes of this act, the following definitions apply.\n\n"
    "Chapter A General Provisions\nThese provisions are general in nature and apply broadly.\n\n"
    "Section 3 Applicability\nThis section covers applicability across all residents."
)

_SAMPLE_STRATEGY_TEXT = (
    "Asset allocation is the process of dividing investments among different asset categories.\n\n"
    "Equity investments provide long-term growth and are suitable for investors with high risk tolerance.\n\n"
    "Debt instruments offer stability and regular income, making them ideal for conservative investors.\n\n"
    "Rebalancing ensures the portfolio stays aligned with the target allocation over time."
)


def test_chunk_text_tax_source_max_chars():
    chunks = chunk_text(_SAMPLE_TAX_TEXT, "tax")
    assert all(len(c) <= 2500 for c in chunks), "All chunks must be ≤ 2500 chars"


def test_chunk_text_tax_source_non_empty():
    chunks = chunk_text(_SAMPLE_TAX_TEXT, "tax")
    assert len(chunks) > 0
    assert all(c.strip() for c in chunks)


def test_chunk_text_strategy_source_max_chars():
    chunks = chunk_text(_SAMPLE_STRATEGY_TEXT, "strategy")
    assert all(len(c) <= 2500 for c in chunks)


def test_chunk_text_strategy_source_non_empty():
    chunks = chunk_text(_SAMPLE_STRATEGY_TEXT, "strategy")
    assert len(chunks) > 0


def test_chunk_text_overlap_present():
    """A long chunk that must be split should produce overlap between adjacent sub-chunks."""
    long_text = "A" * 3000  # 3000 chars > CHUNK_MAX_CHARS=2500, so will be split
    chunks = chunk_text(long_text, "strategy")
    assert len(chunks) >= 2, "Long text should produce multiple chunks"
    # The end of chunk[0] and start of chunk[1] should share CHUNK_OVERLAP_CHARS chars.
    from app.ai.ingest import CHUNK_MAX_CHARS, CHUNK_OVERLAP_CHARS
    overlap_start = CHUNK_MAX_CHARS - CHUNK_OVERLAP_CHARS
    assert chunks[0][overlap_start:] == chunks[1][:CHUNK_OVERLAP_CHARS]


# ---------------------------------------------------------------------------
# ensure_collections idempotency tests
# ---------------------------------------------------------------------------

def test_ensure_collections_skips_create_if_exists():
    """If get_collection succeeds, create_collection must NOT be called."""
    mock_client = MagicMock()
    mock_client.get_collection.return_value = MagicMock()  # exists
    ensure_collections(mock_client)
    mock_client.create_collection.assert_not_called()


def test_ensure_collections_creates_if_missing():
    """If get_collection raises, create_collection should be called once per collection."""
    mock_client = MagicMock()
    mock_client.get_collection.side_effect = Exception("not found")
    ensure_collections(mock_client)
    assert mock_client.create_collection.call_count == 2  # one per corpus

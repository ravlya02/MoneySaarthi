"""RAG pipeline over Qdrant (§C.2). Authoritative for RULES only.

Two corpora: tax_law_kb, portfolio_strategy_kb. Tax passages MUST be filtered
by effective_ay so a query for AY 2026-27 never retrieves stale slabs.
"""

from dataclasses import dataclass

TAX_CORPUS = "tax_law_kb"
STRATEGY_CORPUS = "portfolio_strategy_kb"

RETRIEVE_K = 20
RERANK_TO = 6


@dataclass
class Passage:
    corpus: str
    doc_title: str
    section: str
    source_url: str
    text: str


def embed(text: str) -> list[float]:
    """Embed with the Gemini embedding model (same model for index + query)."""
    raise NotImplementedError


def retrieve_tax_passages(query: str, effective_ay: str) -> list[Passage]:
    """Vector search in tax_law_kb with payload filter
    corpus = tax_law_kb AND effective_ay = <ay>, then rerank to top RERANK_TO.
    Refuse to surface passages whose effective_ay doesn't match."""
    raise NotImplementedError


def retrieve_strategy_passages(query: str) -> list[Passage]:
    raise NotImplementedError

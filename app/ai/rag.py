"""RAG pipeline over Qdrant (§C.2). Authoritative for RULES only.

Two corpora: tax_law_kb, portfolio_strategy_kb. Tax passages MUST be filtered
by effective_ay so a query for AY 2026-27 never retrieves stale slabs.
"""

import logging
from functools import lru_cache

from google import genai
from google.genai import types as genai_types
from qdrant_client import QdrantClient
from qdrant_client.http.models import FieldCondition, Filter, MatchValue

from app.config import get_settings
from app.models.reports import Passage

logger = logging.getLogger(__name__)

TAX_CORPUS = "tax_law_kb"
STRATEGY_CORPUS = "portfolio_strategy_kb"

RETRIEVE_K = 20
RERANK_TO = 6

EMBED_MODEL = "models/gemini-embedding-2"


@lru_cache(maxsize=1)
def _qdrant_client() -> QdrantClient:
    s = get_settings()
    return QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key)


def embed(text: str) -> list[float]:
    """Embed with Gemini gemini-embedding-2. Same model for index and query."""
    s = get_settings()
    client = genai.Client(api_key=s.gemini_api_key)
    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=text,
        config=genai_types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
    )
    return result.embeddings[0].values


def retrieve_tax_passages(query: str, effective_ay: str) -> list[Passage]:
    """Vector search in tax_law_kb filtered by effective_ay, reranked to RERANK_TO.
    Returns [] on any Qdrant exception so RAG failure never aborts report generation."""
    try:
        vector = embed(query)
        client = _qdrant_client()
        result = client.query_points(
            collection_name=TAX_CORPUS,
            query=vector,
            limit=RETRIEVE_K,
            query_filter=Filter(
                must=[FieldCondition(key="effective_ay", match=MatchValue(value=effective_ay))]
            ),
        )
        hits = sorted(result.points, key=lambda h: h.score, reverse=True)
        return [
            Passage(
                corpus=TAX_CORPUS,
                doc_title=h.payload.get("doc_title", ""),
                section=h.payload.get("section", ""),
                source_url=h.payload.get("source_url", ""),
                effective_ay=h.payload.get("effective_ay"),
                text=h.payload.get("text", ""),
            )
            for h in hits[:RERANK_TO]
        ]
    except Exception:
        logger.warning("RAG: tax_law_kb retrieval failed", exc_info=True)
        return []


def retrieve_strategy_passages(query: str) -> list[Passage]:
    """Vector search in portfolio_strategy_kb (no effective_ay filter), reranked to RERANK_TO.
    Returns [] on any Qdrant exception."""
    try:
        vector = embed(query)
        client = _qdrant_client()
        result = client.query_points(
            collection_name=STRATEGY_CORPUS,
            query=vector,
            limit=RETRIEVE_K,
        )
        hits = sorted(result.points, key=lambda h: h.score, reverse=True)
        return [
            Passage(
                corpus=STRATEGY_CORPUS,
                doc_title=h.payload.get("doc_title", ""),
                section=h.payload.get("section", ""),
                source_url=h.payload.get("source_url", ""),
                effective_ay=None,
                text=h.payload.get("text", ""),
            )
            for h in hits[:RERANK_TO]
        ]
    except Exception:
        logger.warning("RAG: portfolio_strategy_kb retrieval failed", exc_info=True)
        return []

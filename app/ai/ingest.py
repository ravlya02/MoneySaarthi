"""Corpus ingestion script: PDFs → Qdrant collections (§C.2).

Run once (or after document updates):
    python -m app.ai.ingest

Re-running is safe — deterministic UUID5 point IDs cause upserts, not duplicates.
NOT called during report generation.
"""

import re
import time
import uuid
from datetime import date
from pathlib import Path

import docx
import pypdf
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, PayloadSchemaType, PointStruct, VectorParams

from app.ai.rag import EMBED_MODEL, STRATEGY_CORPUS, TAX_CORPUS, embed
from app.config import get_settings

CHUNK_MAX_CHARS = 2500
CHUNK_OVERLAP_CHARS = 250
BATCH_SIZE = 100

_UUID_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

_TAX_SPLIT_RE = re.compile(r"(?=\bSection\s+\d+|\bChapter\s+[A-Z\d]+|\n\d+\.\s)")


def _qdrant_client() -> QdrantClient:
    s = get_settings()
    return QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key)


def ensure_collections(client: QdrantClient) -> None:
    """Create tax_law_kb and portfolio_strategy_kb if they do not exist.
    Also ensures a keyword payload index on effective_ay in tax_law_kb so
    filtered queries are accepted by Qdrant Cloud."""
    for name in (TAX_CORPUS, STRATEGY_CORPUS):
        try:
            client.get_collection(name)
        except Exception:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=3072, distance=Distance.COSINE),
                on_disk_payload=True,
            )
    # Idempotent — Qdrant ignores the call if the index already exists.
    client.create_payload_index(
        collection_name=TAX_CORPUS,
        field_name="effective_ay",
        field_schema=PayloadSchemaType.KEYWORD,
    )


def extract_pages(pdf_path: Path) -> list[str]:
    """Return per-page text strings from a PDF."""
    reader = pypdf.PdfReader(str(pdf_path))
    return [page.extract_text() or "" for page in reader.pages]


def extract_docx(docx_path: Path) -> list[str]:
    """Return paragraph text strings from a .docx file (one string per paragraph)."""
    doc = docx.Document(str(docx_path))
    return [para.text for para in doc.paragraphs if para.text.strip()]


def chunk_text(text: str, source: str) -> list[str]:
    """Split text into bounded chunks with overlap.

    source='tax'  → split on section/chapter headings first.
    source=other  → split on paragraph breaks.
    Chunks are capped at CHUNK_MAX_CHARS with CHUNK_OVERLAP_CHARS overlap.
    Short fragments (< 200 chars) are merged into the previous chunk.
    """
    if source == "tax":
        raw_chunks = [c for c in _TAX_SPLIT_RE.split(text) if c.strip()]
    else:
        raw_chunks = [c for c in text.split("\n\n") if c.strip()]

    # Merge very short fragments into the previous chunk.
    merged: list[str] = []
    for chunk in raw_chunks:
        if merged and len(chunk.strip()) < 200:
            merged[-1] += " " + chunk.strip()
        else:
            merged.append(chunk.strip())

    # Enforce hard size limit with sliding-window overlap.
    final: list[str] = []
    for chunk in merged:
        if len(chunk) <= CHUNK_MAX_CHARS:
            final.append(chunk)
        else:
            start = 0
            while start < len(chunk):
                end = start + CHUNK_MAX_CHARS
                final.append(chunk[start:end])
                start = end - CHUNK_OVERLAP_CHARS
                if start >= len(chunk):
                    break

    return [c for c in final if c.strip()]


def build_points(
    chunks: list[str],
    collection: str,
    doc_title: str,
    effective_ay: str | None,
) -> list[PointStruct]:
    """Embed each chunk and construct Qdrant PointStructs with deterministic IDs."""
    points: list[PointStruct] = []
    for i, chunk in enumerate(chunks):
        point_id = str(uuid.uuid5(_UUID_NAMESPACE, f"{collection}|{doc_title}|{i}"))
        vector = embed(chunk)
        points.append(
            PointStruct(
                id=point_id,
                vector=vector,
                payload={
                    "corpus": collection,
                    "doc_title": doc_title,
                    "section": f"chunk_{i}",
                    "jurisdiction": "IN",
                    "effective_ay": effective_ay,
                    "source_url": "",
                    "last_reviewed": date.today().isoformat(),
                    "text": chunk,
                },
            )
        )
        # Brief pause between embed calls to stay within API rate limits.
        time.sleep(0.1)
    return points


def ingest_corpus(client: QdrantClient, collection: str, points: list[PointStruct]) -> None:
    """Upsert points in batches of BATCH_SIZE."""
    for i in range(0, len(points), BATCH_SIZE):
        batch = points[i : i + BATCH_SIZE]
        client.upsert(collection_name=collection, points=batch)
        print(f"  upserted {i + len(batch)}/{len(points)} points into {collection}")


if __name__ == "__main__":
    docs = Path("documents")
    client = _qdrant_client()
    ensure_collections(client)

    # --- Tax knowledge base ---
    tax_pdf = docs / "tax_document.pdf"
    if tax_pdf.exists():
        print(f"Ingesting {tax_pdf} → {TAX_CORPUS}")
        pages = extract_pages(tax_pdf)
        full_text = "\n\n".join(pages)
        chunks = chunk_text(full_text, "tax")
        print(f"  {len(chunks)} chunks")
        points = build_points(chunks, TAX_CORPUS, "Income Tax Act 2025", "AY 2026-27")
        ingest_corpus(client, TAX_CORPUS, points)
    else:
        print(f"WARNING: {tax_pdf} not found — skipping tax corpus")

    # --- Portfolio strategy knowledge base ---
    inv_docx = docs / "Advisor_Knowledge_Base.docx"
    if inv_docx.exists():
        print(f"Ingesting {inv_docx} → {STRATEGY_CORPUS}")
        paragraphs = extract_docx(inv_docx)
        full_text = "\n\n".join(paragraphs)
        chunks = chunk_text(full_text, "strategy")
        print(f"  {len(chunks)} chunks")
        points = build_points(chunks, STRATEGY_CORPUS, "Advisor Knowledge Base", None)
        ingest_corpus(client, STRATEGY_CORPUS, points)
    else:
        print(f"WARNING: {inv_docx} not found — skipping portfolio corpus")

    print("Ingestion complete.")

# Spec: RAG Pipeline

## Overview
Implements the RAG pipeline (§C.2) so the AI orchestrator can ground Gemini's narrative in
authoritative domain knowledge: Indian tax law (Income Tax Act 2025, AY 2026-27 slabs,
deductions, capital-gains treatment) and portfolio-management strategy (asset-allocation
frameworks, rebalancing rules, goal-based investing playbooks). The pipeline ingests the two
reference PDFs from `documents/` into two Qdrant Cloud collections (`tax_law_kb` and
`portfolio_strategy_kb`), implements Gemini-embedding-based retrieval with payload filtering
to prevent cross-AY retrieval of stale tax slabs, reranks to 4–6 passages per query, and
wires the resulting context block into the orchestrator's prompt assembly. This unblocks
the full AI synthesis step: Gemini can now cite authoritative rules rather than
hallucinating them.

## Depends on
- Step 02 — Database schema and Supabase clients (service_role key, env vars)
- Step 07 — Web-Search Agent (`EngineOutput`, `MarketFact` models in `app/models/reports.py`;
  `enrich_and_synthesize` entry point in `app/ai/orchestrator.py`)

## Architecture phase
**Compute** — runs inside `generate_report()` background worker, after the deterministic
engine and alongside the web-search agent, before Gemini synthesis (Phase 2 of §A.3).

## Routes
No new routes.

## Database changes
No database changes. Qdrant Cloud is the vector store; no Supabase tables are added.

## Pydantic models

**Modify:** `app/models/reports.py`
- Promote `Passage` from a `@dataclass` in `app/ai/rag.py` to a proper Pydantic model so
  it can be serialised into the prompt:

```python
class Passage(BaseModel):
    corpus: str           # 'tax_law_kb' | 'portfolio_strategy_kb'
    doc_title: str
    section: str
    source_url: str
    effective_ay: str | None = None   # None for portfolio passages
    text: str
```

**No other model changes.**

## Templates
No template changes.

## Engine / AI changes

### `app/ai/rag.py` — full implementation (replaces all `NotImplementedError` stubs)

#### Qdrant client helper
```python
def _qdrant_client() -> QdrantClient:
    """Singleton Qdrant client built from settings.qdrant_url + settings.qdrant_api_key."""
```

#### Embedding
```python
def embed(text: str) -> list[float]:
    """Embed with Gemini gemini-embedding-2.
    Same model is used for both indexing and queries so vector spaces match.
    Uses google.generativeai.embed_content(model='models/gemini-embedding-2', ...).
    """
```

#### Retrieval
```python
def retrieve_tax_passages(query: str, effective_ay: str) -> list[Passage]:
    """
    1. embed(query) → query vector
    2. Qdrant search on 'tax_law_kb' collection:
       - vector similarity (cosine), top RETRIEVE_K=20
       - payload filter: effective_ay = <effective_ay>
    3. Rerank: sort by score descending, return top RERANK_TO=6 as Passage objects.
    4. If fewer than RERANK_TO results, return what was found (never pad or invent).
    5. Raises QdrantCollectionError? No — returns [] on any Qdrant exception (logs warning).
    """

def retrieve_strategy_passages(query: str) -> list[Passage]:
    """
    Same as above but targets 'portfolio_strategy_kb' collection, no effective_ay filter.
    Returns top RERANK_TO=6 passages.
    """
```

### `app/ai/ingest.py` — NEW: corpus ingestion script

This module handles one-time (and re-indexable) ingestion of source PDFs into Qdrant.
It is a standalone script (`python -m app.ai.ingest`), not called during report generation.

#### Key responsibilities:
1. **Collection management** — `ensure_collections()`: creates `tax_law_kb` and
   `portfolio_strategy_kb` in Qdrant with cosine distance if they do not exist. Stores
   embedding model name in collection metadata so a model change forces a re-index.

2. **PDF parsing** — `extract_pages(pdf_path: Path) -> list[str]`: uses `pypdf` to read
   pages as text strings.

3. **Semantic chunking** — `chunk_text(text: str, source: str) -> list[str]`: splits on
   section/clause boundaries for tax law (regex on headings like `"Section \d+"`,
   `"Chapter \w+"`, numbered clauses) and on paragraph breaks for strategy docs. Targets
   300–500 tokens (~1500–2500 chars) with ~50-token (~250-char) overlap. Never splits
   mid-sentence within a clause.

4. **Point construction** — each chunk becomes one Qdrant point:
   - `id`: deterministic UUID derived from `(collection, doc_title, chunk_index)` so
     re-ingestion upserts rather than duplicating.
   - `vector`: `embed(chunk_text)`
   - `payload`: `{ corpus, doc_title, section, jurisdiction:'IN', effective_ay,
                   source_url, last_reviewed, text }`

5. **Batch upsert** — `ingest_corpus(collection: str, points: list[PointStruct])`:
   upserts in batches of 100 using `client.upsert()`.

6. **Entry point** — `__main__` block ingests both PDFs:
   ```
   tax_document.pdf      → tax_law_kb       (effective_ay = 'AY 2026-27')
   Investment_analysis…  → portfolio_strategy_kb  (effective_ay = None)
   ```

### `app/ai/orchestrator.py` — wire in RAG passages

Update `enrich_and_synthesize` to call both RAG functions and pass results to
`build_prompt`:

```python
# Build queries from engine output
tax_query     = f"tax slabs deductions AY 2026-27 income {engine.tax_result.recommended_regime}"
strategy_query = f"asset allocation rebalancing {engine.target_allocation} risk profile"

tax_passages      = retrieve_tax_passages(tax_query, effective_ay=settings.assessment_year)
strategy_passages = retrieve_strategy_passages(strategy_query)
```

Pass `tax_passages` and `strategy_passages` to `build_prompt()`.

### `app/ai/prompts.py` — render `[KNOWLEDGE BASE]` section

Update `build_prompt(engine, market_data, tax_passages, strategy_passages)` to append:

```
[KNOWLEDGE BASE]  (RAG from Qdrant — authoritative for RULES only)
<passage.section>: <passage.text>
...
```

Include up to `RERANK_TO` tax passages then up to `RERANK_TO` strategy passages.
Each passage rendered as `{section}: {text}` on one line (no source URL in the prompt —
it is stored in the Passage object for the audit trail, not injected into Gemini's context).

## Files to change
- `app/ai/rag.py` — full implementation (replaces all `NotImplementedError` stubs)
- `app/ai/orchestrator.py` — call `retrieve_tax_passages` + `retrieve_strategy_passages`;
  pass passages to `build_prompt`
- `app/ai/prompts.py` — add `tax_passages` and `strategy_passages` parameters; render
  `[KNOWLEDGE BASE]` section
- `app/models/reports.py` — add `Passage` Pydantic model; remove `@dataclass` from `rag.py`
- `requirements.txt` — add `pypdf>=4`

## Files to create
- `app/ai/ingest.py` — corpus ingestion script
- `tests/test_rag.py` — unit tests (see Definition of Done)

## New dependencies
```
pypdf>=4
```
Add to `requirements.txt`. (`qdrant-client` and `google-generativeai` are already listed.)

## Rules for implementation
- Use `Decimal` for all money math — never float. This module does not handle money math
  but must not cast any rupee figure to float if encountered during chunk parsing.
- Tax rules must live in `app/engine/tax/rules.py`, keyed by assessment year — the RAG
  corpus is a retrieval source for Gemini's narrative only; it does not replace or modify
  the deterministic rules module.
- Gemini writes narrative only; it must never compute or invent a rupee figure — retrieved
  passages provide rule context, not numbers. The `[KNOWLEDGE BASE]` block must contain
  only law text and strategy principles, never rupee figures that Gemini could echo back
  as "computed".
- After Gemini responds, run the numeric-consistency check in `app/ai/validation.py` —
  this module feeds passages *to* the prompt; the check runs downstream.
- RLS is enforced on every user Supabase table; Qdrant collections contain only public
  knowledge (no PII) and have no per-user access control.
- `service_role` key is used only in the background worker — this module uses it for
  Qdrant access (via settings), not for any Supabase user-data query.
- All templates extend `app/templates/base.html` — this module has no templates.
- The `embed()` function must use `models/gemini-embedding-2` (the same model for both
  indexing in `ingest.py` and querying in `rag.py`). If the model name changes,
  the entire corpus must be re-indexed. Store the model name in Qdrant collection metadata.
- `retrieve_tax_passages` must NEVER return passages with `effective_ay` different from the
  requested AY, enforced via Qdrant payload filter — not just application-layer filtering.
- Chunk deterministic IDs (UUID5 from `(collection, doc_title, chunk_index)`) so re-running
  `ingest.py` upserts cleanly without duplicating points.
- On any Qdrant exception (connection error, collection not found) in the retrieval path,
  log a warning and return `[]` — do not let RAG failure abort report generation; the
  orchestrator degrades gracefully to "knowledge base unavailable".
- Passage text injected into the prompt must be kept to the reranked top 4–6 entries to
  keep prompt size bounded (§E.1 prompt-size discipline).
- Plotly figures are built server-side, serialized with `pio.to_json`, hydrated client-side
  with `Plotly.newPlot` — no iframes or static images (not directly relevant here, but
  remains a project-wide rule).

## Definition of done
- [ ] `pytest tests/test_rag.py` passes all tests without a live Qdrant connection (Qdrant
  client is mocked; embedding function is mocked to return a fixed 3072-dim vector).
- [ ] `retrieve_tax_passages` issues a Qdrant search with a payload filter containing
  `effective_ay = 'AY 2026-27'` (verified by inspecting the mock call args in tests).
- [ ] `retrieve_strategy_passages` issues a Qdrant search on `portfolio_strategy_kb` with
  no `effective_ay` filter (verified in tests).
- [ ] Both retrieval functions return `[]` (not raise) when the Qdrant client raises any
  exception (tested with a mock that raises `Exception("connection refused")`).
- [ ] `retrieve_tax_passages` returns at most `RERANK_TO=6` passages even when the mock
  Qdrant returns 20 results.
- [ ] `Passage` is importable from `app.models.reports`, is a Pydantic `BaseModel`, and
  `.model_dump()` / `.model_json_schema()` work without error.
- [ ] `app/ai/rag.py` imports without error when `QDRANT_URL` and `QDRANT_API_KEY` are
  empty strings (clients are only instantiated at call time, not at import time).
- [ ] `app/ai/ingest.py` runs without error in a dry-run mode (mock Qdrant + mock embed):
  `chunk_text` produces chunks of ≤ 2500 characters with ≥ 250-character overlap on a
  sample paragraph (verified by unit test in `tests/test_rag.py`).
- [ ] `ensure_collections()` calls `client.create_collection` only if the collection does
  not already exist (idempotent — verified by mock showing `create_collection` is called
  once and skipped on a second run).
- [ ] `build_prompt` in `app/ai/prompts.py` includes a `[KNOWLEDGE BASE]` section when
  non-empty passage lists are passed (verified by a unit test that checks the returned
  string for the `[KNOWLEDGE BASE]` header and at least one passage's section text).
- [ ] `enrich_and_synthesize` in `app/ai/orchestrator.py` calls both
  `retrieve_tax_passages` and `retrieve_strategy_passages` (verified by mocking both
  functions and asserting they are called with non-empty query strings).
- [ ] `pytest tests/` shows all 33 existing tests (plus new ones) green after the changes.

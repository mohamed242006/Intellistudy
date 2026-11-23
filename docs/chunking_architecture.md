# Chunking Layer: Architecture, Implementation and Integration Notes

> **STATUS: HISTORICAL (superseded in part, banner added 2026-11-15).** Kept for design context: it records the
> chunking architecture as first built (class split, SOLID rationale, integration plan). The text below is unchanged.
> The current single source of truth is [`project_context.md`](project_context.md). Outdated here:
> - **Chunk ID format** `{doc_id}-{ordinal:05d}-{hash8}` and §4 note 6 ("inserting a section early shifts later ids"):
>   replaced in chunker 1.3.0 by content ids `c-{hash12}` / `p-{hash12}` that survive edits (E2E-08) - see
>   project_context.md §3.2 and §5, and [`answer_layer.md`](answer_layer.md) §1.
> - **Chunker version** (implied 1.0.0): current is **1.3.0** - project_context.md §3.2.
> - **Schema version** 2.x as "2.0": current is **2.1** (figure fields) - project_context.md §3.1.
> - **Figure chunks**: the `figure` chunk kind (chunker 1.2.0) is not described here - project_context.md §3.8.
> - **Embedding and vector store** (§5.1, §5.2, §7 "Not yet built", "sentence-transformers/torch not installed"):
>   `BgeEmbedder` and `ChromaVectorStore` are built and tested - project_context.md §3.3 and §3.4.
> - **Retrieval and reranking** (§7 "not yet built"): built, with an optional cross-encoder reranker and a calibrated
>   relevance policy - project_context.md §3.5.
> - **Prompt builder / answer layer** (§7 "not yet built"): built (MVP) and evaluated on one real model
>   (Qwen2.5-3B) - project_context.md §3.10 and §11.
> - **Test counts** ("215 tests"): see project_context.md §6 for the current verified figures.

Companion to `chunking_design_spec.md` (rules) - this file describes the code in `ai/chunking/` as built.
Status: implemented, 215 tests green (whole repository), validated on schema 2.0 documents from the real ingestion pipeline.

## 1. Architecture

```
Document (schema 2.x)                      ChunkContext (user, course, document_uid, embedding_model)
        |                                              |
        v                                              v
 BlockSelector --> build_sections --> ChunkBuilder --> ParentBuilder --> ChunkValidator
 (exclusion        (leaf heading_path,   (AtomBuilder,     (section-level       (invariants,
  rules)            slide = section)      TextSplitter:     parents; links       strict or
                                          pack/merge/       children)            report-only)
                                          overlap/ids)
                                  \_____________ ChunkingEngine (composition root) _____________/
                                                          |
                                                          v
                                       ChunkSet(parents, children, report)
                                                          |
        Embedder (protocol)  <--  IndexingService  -->  VectorStore (protocol)
        any model                 ReingestPlanner         ChromaDB adapter / InMemoryVectorStore
```

### Class responsibilities (SOLID)

| Class | Single responsibility | Depends on (abstraction) |
|---|---|---|
| `ChunkConfig` | Immutable parameters (400 / 480 / 60 tokens, thresholds); validates itself | - |
| `TokenCounter` (protocol), `ApproxTokenCounter`, `HFTokenCounter` | Count tokens in the **embedding model's** units | - |
| `BlockSelector` | Which blocks are eligible (hidden slides, OCR < 0.3, empty) | `ChunkConfig` |
| `build_sections` | Group blocks by leaf `heading_path`; every slide is its own section | - |
| `TextSplitter` | Sentence-bounded splitting and overlap tails | `TokenCounter` |
| `AtomBuilder` | Blocks -> atoms (list, table, chart, notes, OCR); split oversize atoms | `TokenCounter`, `TextSplitter` |
| `ChunkBuilder` | Pack atoms, merge small chunks, attach overlap, build `ChildChunk` (ids, metadata, citations) | `AtomBuilder`, `TextSplitter`, `TokenCounter` |
| `ParentBuilder` | Group children into `ParentChunk`s and link them | `TokenCounter` |
| `ChunkValidator` | Check invariants on a finished result | `BlockSelector` |
| `ChunkingEngine` | Compose the above; public API; strict/lenient policy | all of the above, injectable |
| `ReingestPlanner` | Pure diff between stored vectors and new chunks | - |
| `IndexingService` | Embed what is new, upsert, delete stale | `Embedder`, `VectorStore` |
| `Embedder`, `VectorStore` (protocols) | The only coupling points to models and databases | - |

* **Open/closed**: every collaborator can be replaced via the `ChunkingEngine` constructor (a different selector, builder, validator) without touching the others.
* **Dependency inversion**: the chunker imports no embedding library and no database client. `Embedder` and `VectorStore` are `Protocol`s; swapping BGE for another model, or ChromaDB for another store, changes one adapter and the `embedding_model` string.
* **Model-agnostic**: the embedding model only influences (a) the `TokenCounter` you pass, (b) `max_tokens`, (c) the collection name. Changing model = new collection (`collection_name(model)`), re-embedding all chunks; chunk **ids and text do not change**.

### Models

```
Chunk (frozen base)         ChildChunk(Chunk)                ParentChunk(Chunk)
 chunk_id, ordinal, kind     parent_id                        child_ids
 text, token_count           embedding_text (prefix+overlap   (kind = "section"; never embedded)
 content_hash                  +text), overlap_prefix
 doc_id, document_uid,       embedding_hash (reuse key)
  sha256, file_name,         has_table, table_index/part/parts
  file_type, unit            embedding_model, oversize
 title, author, created,
  modified, language
 user_id, course_id
 page_start/end (page_number), slide_number
 heading_path, section_titles
 block_start/end, block_orders, block_ranges, block_types
 citation_label, bboxes
 confidence, ocr_confidence, low_confidence, source_kind
 chunker_version, schema_version, tokenizer
```

Required metadata of the final decisions is all present: `chunk_id, doc_id, heading_path, citation_label, page_number, slide_number, block_ranges, block_types, ocr_confidence`, plus document metadata (`title, author, language, file_name, file_type, created, modified`). `ChildChunk.chroma_metadata()` flattens them to scalars (lists as strings, `None` as `-1`/`""`).

## 2. Folder structure

```
ai/chunking/
  __init__.py      public API
  config.py        EMBEDDING_MODEL, QUERY_INSTRUCTION, ChunkConfig, collection_name()
  tokens.py        TokenCounter protocol + Approx / HF implementations
  ids.py           content_hash, make_chunk_id, vector_id
  citation.py      citation_label, block_ranges
  render.py        single table renderer (markdown for display, key/value for embedding)
  models.py        Chunk, ChildChunk, ParentChunk, ChunkContext, ChunkReport, ChunkSet
  errors.py        ChunkingError, ChunkValidationError, IndexingError
  text.py          TextSplitter
  selection.py     BlockSelector
  sections.py      Section, build_sections
  atoms.py         Atom, AtomBuilder
  builder.py       ChunkBuilder
  parents.py       ParentBuilder
  validation.py    ChunkValidator
  engine.py        ChunkingEngine
  interfaces.py    Embedder, VectorStore, VectorRecord, ScoredRecord
  indexing.py      ReingestPlanner, IndexingService
  memory_store.py  InMemoryVectorStore (tests / dev / reference implementation)
tests/
  chunk_fixtures.py       synthetic documents, WordCounter, FakeEmbedder
  test_chunker.py         engine behaviour (sections, packing, overlap, tables, slides, OCR, ids)
  test_chunk_rules.py     one test per FINAL decision
  test_chunk_models.py    schema / metadata
  test_chunk_parents.py   hierarchy
  test_chunk_validation.py  validator + real PDF/DOCX/PPTX compatibility (step 6)
  test_chunk_indexing.py  re-ingestion, no duplicates, scoping
```

## 3. Final decisions, where they are enforced

| Decision | Code |
|---|---|
| Sections from leaf `heading_path`; slides independent | `sections.build_sections` |
| 400 target / 480 hard / ~60 overlap | `ChunkConfig`, `ChunkBuilder._section_drafts`, `TextSplitter.tail` |
| Overlap only between text chunks of one section | `ChunkBuilder._finalise`; verified by `ChunkValidator._overlap` |
| Never overlap tables, notes, charts | `ISOLATED_KINDS` (own chunks, never merged) |
| Headings never standalone | `AtomBuilder.build` skips headings |
| Lists together; tables / charts / notes / OCR atomic | `AtomBuilder` (split only above the hard limit) |
| Tables <= 400 stay whole; split by rows, header repeated, context kept | `AtomBuilder._split_table`, `_table_atom` |
| Hidden slides excluded; title-only not indexed; notes separate | `BlockSelector`, `ChunkBuilder._section_drafts` |
| OCR labelled, confidence kept, < 0.6 flagged, < 0.3 not indexed | `AtomBuilder._labelled`, `ChunkBuilder._confidences`, `BlockSelector` |
| Deterministic ids `{doc_id}-{ordinal:05d}-{hash8}` | `ids.make_chunk_id` |
| Re-ingestion without duplicate vectors | `ReingestPlanner`, `IndexingService` |

## 4. Implementation notes and deviations found while building

1. `include_hidden` was removed from `ChunkContext` (hidden slides are always excluded, per the final decision).
2. Charts are now isolated like tables and notes (needed for "never overlap charts").
3. Image OCR between 0.3 and 0.6 is indexed and flagged (earlier draft dropped below 0.55). Note that the ingestion `OCRProcessor` itself already discards image OCR below 55 / 100, so in practice the 0.3-0.55 band only reaches the chunker if that threshold is lowered.
4. Page confidence is used to drop or flag **only** whole-page OCR pages of PDFs; for DOCX/PPTX it describes images only.
5. Title-only threshold is 6 tokens: a slide with fewer than 6 body tokens and no table/chart/image text is treated as a divider. This also drops a slide whose only content is one very short bullet; raise or lower `slide_min_body_tokens` if that is not wanted.
6. Chunk ids include the ordinal, so inserting a section early shifts later ids. The planner therefore reuses stored vectors by `embedding_hash`, so only genuinely new text is embedded.
7. `embedding_hash` (hash of `embedding_text`) rather than `content_hash` decides reuse, because heading prefix and overlap are part of what is embedded.

## 5. Integration notes

### 5.1 Embeddings (`BAAI/bge-small-en-v1.5`, 384-d, 512-token window)

```python
from sentence_transformers import SentenceTransformer
from ai.chunking import EMBEDDING_MODEL
from ai.chunking.config import QUERY_INSTRUCTION

class BgeEmbedder:                       # satisfies ai.chunking.Embedder
    model_name = EMBEDDING_MODEL
    dimension = 384
    def __init__(self):
        self._model = SentenceTransformer(EMBEDDING_MODEL)
    def embed_documents(self, texts):    # documents: NO instruction
        return self._model.encode(list(texts), normalize_embeddings=True, batch_size=32).tolist()
    def embed_query(self, text):         # queries: instruction prefix
        return self._model.encode(QUERY_INSTRUCTION + text, normalize_embeddings=True).tolist()
```
* Pass `default_token_counter()` (uses the model's tokenizer) to `ChunkingEngine` so budgets are exact; `max_tokens=480` leaves room for the two special tokens inside the 512 window.
* Set `ChunkContext.embedding_model = EMBEDDING_MODEL`; `IndexingService` refuses chunks prepared for a different model.
* `sentence-transformers` / `torch` are not installed in the project environment yet: add them to pinned requirements and run embedding in the worker, not the API process.

### 5.2 ChromaDB

Write `ChromaVectorStore` implementing `VectorStore`:

* collection: `collection_name(EMBEDDING_MODEL)` -> `chunks__bge-small-en-v1.5__c1`, created with `metadata={"hnsw:space": "cosine"}`.
* `upsert`: `collection.upsert(ids=[r.id], embeddings=[r.embedding], documents=[r.document], metadatas=[r.metadata])`. `ChildChunk.chroma_metadata()` already contains only scalars.
* `list_ids(document_uid)`: `collection.get(where={"document_uid": uid}, include=["metadatas"])` -> `{id: metadata["embedding_hash"]}`.
* `get_embeddings(ids)`: `collection.get(ids=ids, include=["embeddings"])`.
* `delete(ids)`: `collection.delete(ids=ids)`.
* `query`: **always** `where={"$and": [{"user_id": u}, {"course_id": c}, *filters]}`; refuse calls without `user_id`/`course_id` (FR-RAG-03). Convert distance to similarity (`1 - distance`).
* Reference behaviour to match: `InMemoryVectorStore` and `tests/test_chunk_indexing.py` - run the same test-suite against the Chroma adapter.

### 5.3 Retrieval, citations, RAG

1. Embed the query (`embed_query`), `store.query(...)` top-20, optional cross-encoder rerank to 5.
2. Each hit carries `citation_label`, `page_number`/`slide_number`, `heading_path`, `block_ranges`, `parent_id`, `low_confidence`.
3. Context expansion: fetch the parent (`document_chunks`/parents table by `parent_id`, ADR-009) when a hit needs surrounding text; use `text`, never `embedding_text`, in prompts.
4. Citation markers `[C1..Ck]` map to `chunk_id`; store citations with `chunk_id` + `document_uid`. Highlighting uses `block_ranges` (re-open the blocks) and, for PDF, `bboxes` kept in the relational copy.
5. `low_confidence=True` chunks may be down-weighted or trigger a low-confidence answer flag.

### 5.4 Persistence (PostgreSQL, source of truth)

Store `ChildChunk` and `ParentChunk` (`to_record()`), including `text`, `embedding_text`, `bboxes`, `block_orders`. The vector index must be rebuildable from these rows (NFR-REL-07): re-embed `embedding_text` with the recorded `embedding_model`.

### 5.5 Re-ingestion flow

```
doc  = pipeline.ingest(path)                       # schema 2.0
sets = engine.run(doc, ctx)                        # deterministic ChunkSet
persist(sets.parents, sets.children)               # PostgreSQL
IndexingService(embedder, store).index(sets.children, document_uid=ctx.document_uid)
```
* Unchanged file -> `unchanged = n`, nothing embedded, nothing written except no-op.
* Edited section -> only that chunk (and an overlap-affected neighbour) re-embedded; stale id deleted after the upsert.
* Early insertion -> ids shift; vectors reused via `embedding_hash`.
* A failed embedding leaves the store untouched (embed first, upsert second, delete last).
* Retention of superseded relational rows (7 days) is a PostgreSQL job; the vector store keeps no tombstones.

## 6. Verification status

| Check | Result |
|---|---|
| Whole test suite | 215 tests pass (+10 routing tests) |
| Real PDFs (3), DOCX (1) with real BGE tokenizer, strict validation | 0 invariant violations, 0 oversize chunks |
| PDF / DOCX / PPTX through the real ingestion pipeline | covered in `test_chunk_validation.IngestionCompatibilityTests` |

## 7. Not yet built

* `BgeEmbedder` and `ChromaVectorStore` adapters (above; dependencies not installed).
* PostgreSQL persistence for chunks and parents, job runner, retrieval/reranking, prompt builder.
* Per-job isolation of the ingestion pipeline (still a prerequisite for parallel uploads).
* Arabic support (model and OCR are English only).

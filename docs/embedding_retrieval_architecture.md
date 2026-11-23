# Embedding, Vector Storage and Retrieval

> **STATUS: HISTORICAL (superseded in part, banner added 2026-11-15).** Kept as the design record of the embedding,
> Chroma and parent-child retrieval layers; the text below is unchanged and its architecture still holds. The current
> single source of truth is [`project_context.md`](project_context.md). Outdated here:
> - **Reranker status** (§G "No reranker"): an optional cross-encoder reranker (`ai/retrieval/rerank.py`), bibliography
>   demotion and a calibrated, model-bound relevance assessment exist - project_context.md §3.5 and
>   [`phase0_report.md`](phase0_report.md) §2.
> - **Chunk ID format / re-ingestion wording** ("ordinals shifted" -> reuse): chunk ids are content-based
>   `c-{hash12}` / `p-{hash12}` since chunker 1.3.0 - project_context.md §3.2 and §3.6.
> - **Chunker version** (implied 1.x before 1.3.0) and **schema version** (2.0): current 1.3.0 and 2.1 -
>   project_context.md §3.1-3.2. **Figure chunks** (`kind="figure"`) are indexed like other children - §3.8.
> - **Embedding and vector-store status**: as described here and still current (BGE-small, one Chroma collection per
>   model + chunker major, SQLite parents; PostgreSQL still not built) - project_context.md §3.3-3.4.
> - **Answer layer and real-model evaluation**: not covered here - project_context.md §3.10 and §11.
> - **Test counts** ("334 tests"): see project_context.md §6.

Builds on `chunking_architecture.md`. Status: implemented; 334 tests pass (4 opt-in real-model tests skipped by default and passing when enabled), verified end to end on the real lecture PDFs with `BAAI/bge-small-en-v1.5`, ChromaDB 1.5 and SQLite.

## A. Indexing architecture

```
Document ─► ChunkingEngine ─► ChunkSet(parents, children)
                                   │                    │
                         parents   │                    │ children only
                                   ▼                    ▼
                          ParentStore            IndexingService ──► Embedder (BgeEmbedder)
                       (SQLite / PostgreSQL)          │  ReingestPlanner: diff by embedding_hash
                       no vectors, ever               ▼
                                                 VectorStore (ChromaVectorStore)
```

| Component | Module | Role |
|---|---|---|
| `Embedder` protocol | `ai/chunking/interfaces.py` | `model_name`, `dimension`, `embed_documents`, `embed_query` |
| `BgeEmbedder` | `ai/embedding/bge.py` | BGE conventions: documents plain, queries prefixed with the retrieval instruction, vectors L2-normalised; lazy model load; injectable model/loader |
| `VectorStore` protocol | `ai/chunking/interfaces.py` | `upsert`, `delete`, `list_ids`, `get_embeddings`, `query` (user and course mandatory) |
| `ChromaVectorStore` | `ai/vectorstore/chroma_store.py` | Chroma adapter |
| `ParentStore` protocol | `ai/chunking/interfaces.py` | `put_many`, `get_many` (scoped), `list_ids`, `delete` |
| `SQLiteParentStore`, `InMemoryParentStore` | `ai/storage/`, `ai/chunking/memory_store.py` | parent rows; PostgreSQL later implements the same four methods |
| `IndexingService`, `ReingestPlanner` | `ai/chunking/indexing.py` | embed, upsert, reuse, delete stale |
| `RetrievalService` | `ai/retrieval/service.py` | search + parent expansion |

**Rules enforced in code (and tested):**
* Only `ChildChunk` is embedded. A `ParentChunk` passed to `IndexingService.index` raises `IndexingError`; parents have no `embedding_text` attribute; they are written to the `ParentStore` only.
* Order of operations: embed (nothing is written if the model fails) → write parents → upsert vectors → delete stale vectors → delete stale parents. A retrievable child therefore always has its parent, and a failure leaves the previous index intact.
* Re-ingestion: for each new chunk the planner compares `embedding_hash` with what the store holds for the document: identical id and hash → **unchanged**; hash found under a stale id (ordinals shifted) → **reused** (the stored vector is copied to the new id); otherwise → **embedded**. Stale ids are deleted last. Verified: unchanged file embeds 0 chunks (0.03 s vs 13 s first time on a 35-page PDF).
* The embedder's `model_name` must equal the `embedding_model` recorded on the chunks, and every vector must have `embedder.dimension` entries.

## B. Chroma collection design

* **One collection per embedding model and chunker major version**: `chunks__bge-small-en-v1.5__c1` (`collection_name()`). Changing the model starts a new collection; dimensions are never mixed.
* **Not one collection per user.** Per-user collections do not scale. Isolation is a mandatory metadata filter: `where = {"$and": [{user_id == u}, {course_id == c}, ...filters]}`; the adapter refuses a query without both and refuses filters that try to override them.
* **Our vectors only**: `embedding_function=None`; Chroma never loads a model. Space is cosine (`score = 1 - distance`).
* **Record**: `id = {document_uid}:{chunk_id}`; `document = child.text` (never `embedding_text`); `embedding` supplied by `BgeEmbedder`; flat scalar metadata:

| Key | Meaning |
|---|---|
| `chunk_id`, `parent_chunk_id`, `doc_id`, `document_uid` | identity and hierarchy |
| `heading_path` (" > " joined), `heading_path_json`, `heading_top` | section path / cheap filter |
| `citation_label`, `page_number`, `page_start`, `page_end`, `slide_number` (-1 if none) | citation |
| `block_types` (csv), `block_ranges` ("1-2,5-5"), `kind`, `source_kind` | structure |
| `ocr_confidence` (-1.0 if none), `confidence`, `low_confidence` | quality |
| `user_id`, `course_id` | ownership (filtered on every query) |
| `content_hash`, `embedding_hash`, `embedding_model`, `chunker_version`, ... | re-ingestion and versioning |

* Calls are batched below Chroma's maximum batch size (5,461); `list_ids` pages through results.
* **Why `document_uid` is in every key**: `doc_id` is a content hash, so two users uploading the same file produce identical `chunk_id`s *and* identical parent ids. Vectors are keyed by `{document_uid}:{chunk_id}`; parents use the same key (`ParentChunk.store_key`). (A test with two users and an identical file caught this collision.)

## C. Retrieval flow

```
search(query, user_id, course_id, k, document_uids, filters, min_score,
       include_low_confidence, expand_parents, parent_token_budget)
 1. validate (query not empty, user and course present, k >= 1)
 2. vector  = embedder.embed_query(query)               # BGE instruction added here
 3. records = store.query(collection, vector, user, course, k, filters)
 4. drop records with score < min_score                  # empty result => "not found in your material"
 5. hits    = [RetrievedChunk.from_record(r)]            # best first; no extra lookup needed
```
`RetrievedChunk` carries `chunk_id, parent_chunk_id, score, text, kind, doc_id, document_uid, file_name, heading_path, citation_label, page_number, slide_number, block_types, ocr_confidence, low_confidence, user_id, course_id` (+ raw metadata).

Filters: `document_uids` (list → `$in`), `include_low_confidence=False`, and any metadata key (`{"heading_top": "Caching", "kind": "table"}`); scalar = equals, list = one of.

## D. Parent–child retrieval flow

```
hits (children, best first)
   └─► parent keys = unique "{document_uid}:{parent_chunk_id}" in rank order
         └─► ParentStore.get_many(keys, user_id, course_id)        # scoped again
               └─► ParentContext(parent, hit_chunk_ids, best_score)  # one per parent
```
* `RetrievalResult.hits` = children first (what was matched); `RetrievalResult.parents` = expansion context (the surrounding section), ordered by their best child, each parent returned once even when several children matched.
* `result.parent_for(hit)` links a hit to its context. Prompts should cite with the child's `citation_label` and read the parent's `text` for surrounding explanation.
* Missing parent row → warning, hit still returned. No parent store configured → warning. `parent_token_budget` keeps the best parent and drops lower-ranked ones that would exceed the budget.
* Observation on lecture decks: each slide is its own section, so most parents have one child; expansion pays off on long prose (the proposal PDF) and multi-chunk sections.

## E. Usage

```python
from ai.chunking import ChunkingEngine, ChunkContext, IndexingService, EMBEDDING_MODEL, default_token_counter
from ai.embedding import BgeEmbedder
from ai.vectorstore import ChromaVectorStore
from ai.storage import SQLiteParentStore
from ai.retrieval import RetrievalService

document   = IngestionPipeline().ingest(path)
ctx        = ChunkContext(user_id, course_id, document_uid, EMBEDDING_MODEL)
chunk_set  = ChunkingEngine(tokenizer=default_token_counter(), strict=True).run(document, ctx)

embedder, store, parents = BgeEmbedder(), ChromaVectorStore(path="data/chroma"), SQLiteParentStore("data/parents.sqlite3")
IndexingService(embedder, store, parent_store=parents).index(
    chunk_set.children, document_uid=document_uid, parents=chunk_set.parents)

result = RetrievalService(embedder, store, parents).search(
    "What is separation of concerns?", user_id=user_id, course_id=course_id, k=5, min_score=0.6)
```
Replacing a component: another model = any `Embedder` (new `collection_name`); another vector DB = any `VectorStore`; PostgreSQL parents = any `ParentStore`. None of the chunker, indexer or retriever changes.

## F. Tests

| Suite | What it proves |
|---|---|
| `test_bge_embedder.py` | conventions (no instruction on documents, instruction on queries, normalised), lazy load, dimension checks, replaceable; **real-model** tests (opt-in `INTELLISTUDY_MODEL_TESTS=1`) |
| `test_chunk_indexing.py` | idempotent re-ingestion, reuse after id shifts, no duplicates, failure leaves store untouched, parents never embedded, parent replacement and removal |
| `test_chroma_store.py` | the whole indexing suite re-run on ChromaDB; stored fields; own vectors; cosine; scope; `$in`; batching; persistence |
| `test_parent_store.py` | one contract for in-memory and SQLite: lossless round-trip, scope, replace, delete, rollback, persistence, 1,500-key lookup |
| `test_retrieval.py` | search, top-k, ranking, user and course isolation (incl. identical files of two users), document/metadata filters, `min_score`, low-confidence handling, parent expansion/dedup/order/budget, missing parents, re-ingestion visible in search, real PDF through the pipeline; all on in-memory **and** Chroma + SQLite; plus an opt-in BGE end-to-end test |

## G. Known limits / next steps

* Chroma persistence is single-process (embedded). For several API workers run Chroma as a server and pass an `HttpClient`.
* The embedding runs in-process on CPU (13 s for 52 chunks on this machine); run it in the worker, not the API.
* English only (model and OCR). A `min_score` of about 0.6 separated relevant (0.76-0.85) from unrelated (0.46) queries on the sample lecture; tune it on the evaluation set.
* No reranker, no query rewriting, no hybrid (keyword) search yet; PostgreSQL implementation of `ParentStore` and persistence of chunk rows is still to do.
* Image-OCR text sometimes carries bullet glyph noise (`�`), which slightly lowers its similarity.

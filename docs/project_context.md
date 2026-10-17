# IntelliStudy - Project Context (single source of truth)

**IntelliStudy: AI-Powered Lecture Summarization and Adaptive Exam Generation System using Retrieval-Augmented Generation (RAG)**
Graduation project, Computer Engineering, Ain Shams University, team of four.

> **How to use this file.** It describes what exists in the repository today, why it was built that way,
> how it was validated, and what is still open. Read sections 2-5 before touching `ai/`.
> Assumed reader: an engineer or an AI assistant continuing the work with no other context.
> Last updated: 2026-10-18. Nothing described here has been committed to git yet (see 7 and 10).

Related documents in `docs/`: `chunking_design_spec.md` (approved chunking rules), `chunking_architecture.md`,
`embedding_retrieval_architecture.md`, `validation_progress.md` (validation log), `IntelliStudy_Architecture_Design_v1.1.docx`
(architecture design, Word).

---

## 1. Project Overview

IntelliStudy is an AI-powered educational web platform that helps students study from their own course materials.
Students upload PDF / PPTX / DOCX (optionally audio/video later) and receive:

- structured summaries, citation-grounded question answering, AI tutoring;
- automatic quiz generation and personalized adaptive exams;
- learning analytics: topic mastery, weak-topic detection, study recommendations.

### Main differentiators
1. **Grounded RAG with citations**: every answer is based on uploaded material, with page/slide/section references; unsupported questions are refused.
2. **Adaptive learning engine**: performance-aware assessment generation and a continuous student model.
3. **Weak-topic detection** and **topic mastery scoring** (e.g. Processes 90%, Threads 75%, Deadlocks 35%).
4. **Explain wrong answers** (why wrong, what is correct, what to review).
5. **Personalized exams** (70% weak, 20% medium, 10% strong topics) and **study recommendations**.

Market analysis (ChatGPT, NotebookLM, Quizlet AI, Khanmigo, Studocu AI, CourseHero): summarization, chatbot, QA and quiz generation are
baseline features; grounded citations plus adaptive learning are the differentiators.

### Tech stack
Frontend React + Tailwind (not started) · Backend Python/FastAPI (skeleton only) · AI: sentence-transformers, ChromaDB, RAG ·
DB: PostgreSQL planned (SQLite used now for parent chunks) · Documents: PyMuPDF, python-docx, python-pptx, pdfplumber, Pillow,
Tesseract/pytesseract · Optional speech: Whisper · Deployment: Docker/Compose (not started) · VCS/CI: Git/GitHub Actions (CI not started).

### LLM strategy
Phase 1 ChatGPT API; Phase 2 self-hosted Gemma 3 27B. The architecture stays model-agnostic (an adapter interface) so the swap is small.

---

## 2. Current Architecture

```
Document (PDF / DOCX / PPTX)
  -> Ingestion          ai/ingestion      readers + OCR + table extraction + normalisation
  -> Canonical Blocks   Document / PageContent / Block / SourceInfo (schema 2.0)
  -> Chunking           ai/chunking       sections -> child chunks (indexed) + parent chunks (context)
  -> Embeddings         ai/embedding      BgeEmbedder, BAAI/bge-small-en-v1.5, children only
  -> ChromaDB           ai/vectorstore    one collection per model + chunker major version; parents in SQLite (ai/storage)
  -> Retrieval          ai/retrieval      scoped search -> child hits (best first) + parent expansion + citations
  -> (next) RAG Answer Layer
```

Single entry points:

```python
doc    = IngestionPipeline().ingest("lecture.pdf")                       # ai.ingestion.ingestion_pipeline
chunks = ChunkingEngine(tokenizer=default_token_counter()).run(doc, ChunkContext(user_id, course_id, document_uid, EMBEDDING_MODEL))
IndexingService(BgeEmbedder(), ChromaVectorStore(path=...), parent_store=SQLiteParentStore(...)).index(chunks.children, document_uid=uid, parents=chunks.parents)
result = RetrievalService(embedder, store, parent_store).search("query", user_id=..., course_id=..., k=5)
```

Design principles: one canonical schema for all formats; additive/contract-driven layers; warnings never raise (confidence is the
degradation signal); every chunk carries enough metadata to cite itself; user and course scope is mandatory on every query;
re-ingestion is idempotent and reuses vectors.

---

## 3. Implemented Components

Status legend: DONE = implemented and tested.

### 3.1 Ingestion (`ai/ingestion/`)

**Canonical schema (DONE)** - `models.py`, `structure.py`. Schema version "2.0".
- `Document`: `source: SourceInfo` (doc_id = sha256[:16], sha256, file_name, file_type, size, unit page|slide|document, page_count, parser, ingested_at, title, author, created, modified, language), `metadata`, canonical `statistics`, `pages`.
- `PageContent` (page / slide / always 1 for DOCX): text, ocr_text, final_text, tables, images, confidence 0-1, page_type, warnings, blocks.
- `Block` (the unit chunkers use): type (heading | paragraph | list_item | table | image_ocr | chart | notes), text, page_number, global `order`, `level`, `heading_path` (ancestor titles; a heading's own path ends with itself), `list_marker`, `ref_index`, `bbox`, `confidence`.
- Canonical statistics (same keys for every format): page_count, unit, block_count, heading_count, list_item_count, table_count, image_count, image_ocr_count, chart_count, total_characters, average_confidence, low_confidence_pages (<0.6), warning_count.
- Citation label from `structure.citation_label`: `p. 4 > Caching > LRU`, `slide 4 > ...`, or the heading path for DOCX.
- Why: before this, each reader returned flat text with ad-hoc markers and different metadata; every downstream module would have special-cased formats.

**PDF Reader (DONE)** - `pdf_reader.py`. PyMuPDF text layer; whole-page OCR only when there is no text layer, per-image OCR otherwise. Features, each added because of a real defect in the sample lectures:
- visual-row merging; bullet detection (glyph spans, `o Item`, `- Item`, private-use glyphs) with wrapped-bullet re-joining and nesting depth;
- headings: size >= 1.15 x body or bold single row, <=100 chars, not ending `.,;`; wrapped headings merged; levels from a document-wide `LayoutProfile` (a size must recur on >= 2 pages except in 1-2 page documents); PDF bookmarks override levels;
- **new (2026-10-18)**: text containing inline bullet glyphs, or in a block of 4+ rows, is never a heading (fixed a run-in bullet paragraph in `test2.pdf` being read as two headings);
- running header/footer removal (top/bottom 18% of the page, repeated on >= max(3, 50%) of pages); TOC rows dropped; repeated logo/banner image OCR blanked.

**DOCX Reader (DONE)** - `docs_reader.py`. One logical page, cite by heading path. Body walked once in original order (tables and image OCR appear where they are in the document), `Title` = level 0 and `Heading N` = N, numbering definitions resolved (bullet vs decimal/letter/roman, counters restart), tables rendered key/value with merged cells collapsed, images de-duplicated and OCR'd at the paragraph that references them. Not extracted: headers/footers, footnotes, text boxes.

**PPTX Reader (DONE)** - `pptx_reader.py`. One page per slide; reading order by (top bucket, left), groups expanded; title (also inside groups) emitted once as level-1 heading; bullets/numbering rendered; charts (title, axes, categories, series, legend, type - not values); tables with merge handling; images OCR'd with a per-file sha1 cache; EMF/WMF that cannot be decoded are a mild skip (0.70) not a failure; hidden slides kept and flagged; speaker notes become a `notes` block. **New (2026-10-18)**: slide-number, footer and date placeholders are skipped (they produced junk chunks such as "6").

**OCR (DONE)** - `ocr_processor.py` (Tesseract wrapper, filters for tiny/thin/no-text/low-confidence images, per-document cache) and shared `image_ocr.py` (decode, score, confidence). Image scores: OCR success 0.85-1.0 scaled by engine confidence; intentional skip 0.60-0.85; unsupported format 0.70; error 0.0; page/slide confidence = mean of items, 1.0 when none. English only (`lang="eng"`).

**Table Extraction (DONE)** - `table_extractor.py`: pdfplumber tables for PDF (text re-read excluding table boxes); DOCX and PPTX read tables natively. Rendering as pipe text (default) or key/value.

**Document Builder (DONE)** - `document_builder.py`: finalises PDF pages into blocks, computes confidence (`ConfidenceScorer`) and page type (TEXT/SCANNED/TABLE/MIXED).

**Text normalisation (DONE)** - `cleaners.py`: selective NFKC (keeps superscripts/subscripts, fractions, double-struck sets so STEM text survives), hyphen repair that keeps real compounds, removal of invisible/bidi characters and lone surrogates; applied to PDF, DOCX and PPTX.

**Pipeline (DONE)** - `ingestion_pipeline.py`: routing by extension or MIME type, injectable readers, `IngestionError` family (`PDFParseError`, `DocxParseError`, `PptxParseError`); a failing page/slide becomes an empty page with confidence 0 and a warning. PDF ingestion is serialised with a lock because the PDF layers keep per-document state.

### 3.2 Chunking and parent-child chunking (`ai/chunking/`) - DONE

`ChunkingEngine` = `BlockSelector` -> `build_sections` -> `ChunkBuilder` (`AtomBuilder`, `TextSplitter`) -> `ParentBuilder` -> `ChunkValidator`.

- **Child chunks** (`ChildChunk`) are the only indexed unit. Config: target 400 tokens, hard max 480, overlap 60, heading-prefix cap 60, minimum 80 (small neighbours merge), parent max 1600.
- **Parent chunks** (`ParentChunk`) group children of one section; used only as expansion context at retrieval, never embedded.
- **Atoms** (never split across chunks unless over the hard limit): tables (header repeated on table parts), notes, charts. Over-limit list items / wide rows / charts are split by hard-limit rules; unbreakable tokens split by characters.
- **Slides** never cross a slide boundary; title-only slides (< 6 body tokens, no rich content) are not indexed; hidden slides are excluded.
- **OCR**: image_ocr confidence < 0.3 dropped, < 0.6 kept and flagged `low_confidence`.
- Each chunk carries: ids, `heading_path`, `citation_label`, page/slide range, block ranges and types, kind (text | table | image_ocr | notes | mixed), source kind, OCR confidence, token count, `embedding_text` (heading prefix + body; tables rendered `Column: value`), `embedding_hash`, `record_hash`, parent link.
- Token counting: real BGE tokenizer (`HFTokenCounter`) or approximate counter fallback.

### 3.3 Embeddings and BGE Embedder (`ai/embedding/`) - DONE
`BgeEmbedder`: BAAI/bge-small-en-v1.5 (384-d), lazy model load, documents embedded plain, queries with the BGE retrieval instruction, vectors L2-normalised, NaN/inf/zero vectors rejected, identical texts embedded once per call. `Embedder` is a protocol so other models can be swapped in.

### 3.4 ChromaDB integration and storage (`ai/vectorstore/`, `ai/storage/`) - DONE
- `ChromaVectorStore`: persistent client, **one collection per embedding model + chunker major version** (`chunks__bge-small-en-v1.5__c1`, names sanitised with hash suffix), cosine space, children only, metadata = citation/scope/kind/OCR fields, `vector_id = {document_uid}:{chunk_id}`.
- Mandatory `user_id` + `course_id` scope on every query; filter validation (no operators in values, reserved keys protected).
- `SQLiteParentStore`: parent chunks keyed `document_uid:parent_chunk_id` (no collision between users uploading the same file). PostgreSQL planned.
- `InMemoryVectorStore` / `InMemoryParentStore` (`memory_store.py`) for tests.

### 3.5 Retrieval Service (`ai/retrieval/`) - DONE
`RetrievalService.search(query, user_id, course_id, k, document_uids, filters, min_score, include_low_confidence, expand_parents, parent_token_budget)` returns `RetrievalResult(hits, parents, warnings)`. Children are searched first; parents are attached as expansion context under a token budget; query-vector dimension is validated; each `RetrievedChunk` exposes text (never the embedding text), score, kind, citation_label, heading_path, page/slide, OCR confidence and low-confidence flag.

### 3.6 Re-Ingestion System (`ai/chunking/indexing.py`) - DONE
`IndexingService` + `ReingestPlanner`: embed -> upsert parents -> upsert children -> delete stale. Per chunk the planner decides **unchanged** (same ids and hashes), **refreshed** (metadata changed: `record_hash`), **reused** (same `embedding_hash`, vector copied, no re-embed) or **embedded**. Re-ingesting an unchanged file is a no-op (0.27 s for 3000 chunks); stale chunks are deleted. Tombstone retention decision: 7 days (policy recorded; deletion currently immediate in the stores).

### 3.7 Validation infrastructure - DONE
See section 6. unittest suites, random-document generator, PDF/PPTX fixtures, performance budgets, Ruff/MyPy/coverage configuration in `pyproject.toml`.

---

## 4. Current Folder Structure

```
Intellistudy/
├── ai/
│   ├── ingestion/     models, structure, cleaners, image_ocr, ocr_processor, pdf_reader, table_extractor,
│   │                  document_builder, docs_reader, pptx_reader, ingestion_pipeline
│   ├── chunking/      config, tokens, ids, citation, render, models, text, selection, sections, atoms, builder,
│   │                  parents, validation, engine, interfaces, indexing, memory_store, errors
│   ├── embedding/     bge.py (BgeEmbedder)
│   ├── vectorstore/   chroma_store.py (ChromaVectorStore)
│   ├── storage/       sqlite_parent_store.py (SQLiteParentStore)
│   └── retrieval/     models.py, service.py (RetrievalService)
├── backend/
│   ├── app/           main.py (FastAPI skeleton, GET / only) + empty api/ core/ models/ services/ packages
│   └── requirements.txt   fastapi, uvicorn, pymupdf, python-docx, python-pptx, pdfplumber, pillow, pytesseract, chromadb, sentence-transformers (unpinned)
├── frontend/          empty
├── tests/             27 files: per-module suites + validation suites (chunking, ingestion, embeddings, chroma, reingestion,
│                      retrieval_edge, data_integrity, edge_cases, regression, performance) + fixtures
├── data/uploads/      real sample material (3 lecture/proposal PDFs, 1 PPTX, test.pdf, test2.pdf, test1word.docx, 2 empty .docx)
├── docs/              this file, chunking/embedding specs, validation log, architecture design v1.1 (.docx)
├── pyproject.toml     ruff / mypy / coverage configuration
├── docker-compose.yml EMPTY (no Dockerfile)
├── test_pptx_pipeline.py, test_docs_pipeline.py, test_pipeline.py   routing tests / manual dump scripts
└── .gitignore
```

Environment: Windows 11, Python 3.12, PyMuPDF 1.28, python-pptx 1.0.2, python-docx 1.2, pdfplumber 0.11, Pillow 12,
pytesseract + Tesseract 5.5, chromadb 1.5.9, sentence-transformers 6.0.0, ruff 0.17.1, mypy 2.4.0, coverage 7.16.2, vulture 2.16. pytest is not installed (tests use unittest).

---

## 5. Technical Decisions

| Decision | Choice | Why |
|---|---|---|
| Embedding model | **BAAI/bge-small-en-v1.5** | Small (384-d), fast on CPU, strong English retrieval; approved by the team. English-only, so Arabic needs a different model later. |
| Chunking | **Hierarchical (section -> child -> parent)**, structure-aware, 400/480/60 tokens | Headings give natural boundaries; hard limit keeps within BGE's 512-token window. |
| Retrieval | **Parent-child**: search small children, return parents as context | Small chunks match precisely; parents give the LLM surrounding context. Parents are never embedded. |
| Chunk IDs | **Stable**: `{doc_id}-{ordinal:05d}-{hash8}`, parents `{doc_id}-P{ordinal:04d}-{hash8}`; vector id `{document_uid}:{chunk_id}` | Re-ingestion can diff chunks; ids are unique across users. Content hashes drive reuse. |
| Vector DB | **ChromaDB**, persistent, cosine, one collection per model + chunker major | Embedding model change never mixes vector spaces; scoping done by mandatory user/course metadata. |
| Parent store | SQLite now, PostgreSQL later | Parents are plain records needing lookups by key, not vectors. |
| OCR rules | Tesseract English; image confidence < 0.3 dropped, < 0.6 flagged; repeated logo OCR blanked; EMF/WMF mild skip | Noise must not be indexed; low-confidence text stays visible but flagged for the answer layer. |
| Title-only slides | Not indexed | They add no retrievable content. |
| Hidden slides | Kept by ingestion, excluded by chunking | Consumers choose; students do not expect hidden content in answers. |
| Citation strategy | `citation_label` on every chunk (`p. 14 > 8. Methodology`, `slide 7 > ...`, heading path for DOCX), computed from block page + heading path | Answers must point to a verifiable location. |
| Re-ingestion | `embedding_hash` (vector reuse) + `record_hash` (metadata refresh) + stale deletion, tombstone 7 days | Cheap, idempotent updates; prevents dangling `parent_chunk_id` after edits. |
| Tests | unittest (not pytest) | pytest was not installed; suites also run under pytest. |
| Normalisation | Selective NFKC | Plain NFKC corrupts `x^2`, `H2O`, fractions. |

Historical decisions retained: additive schema (old fields kept), warnings never raise, readers are dependency-injected with a fake-OCR option for tests, per-document state kept local.

---

## 6. Validation Summary

### Quality gates (as of 2026-10-18)
- **586 tests pass** (`python -m unittest discover -s tests -t .`; 6 skipped = opt-in real-model/tooling tests, 1 expected failure = Arabic reversed order) + 10 routing tests in `test_pptx_pipeline.py`.
- **Ruff: clean** (`ruff check ai tests`). `ruff format` has not been applied.
- **MyPy: clean** (0 issues in 41 source files).
- **Coverage: 93% line+branch** (baseline before the validation phase was 90%; measured before the last two small fixes of 2026-10-18).
- Commands: `python -m unittest discover -s tests -t .` · `python -m coverage run --branch -m unittest discover -s tests -t . && python -m coverage report` · `python -m ruff check ai tests` · `python -m mypy ai`. Slow tests: `INTELLISTUDY_SKIP_SLOW=1`; real-model tests: `INTELLISTUDY_MODEL_TESTS=1`.
- Performance (budgets asserted): 3000 chunks indexed in 0.67 s (memory store), 150-page PDF ingested in 2.2 s, 150-slide PPTX 0.8 s, 3000-paragraph DOCX 4.2 s, retrieval over 5000 vectors mean 47 ms / p95 72 ms.

### Defects found and fixed during validation
Hard-limit violations (oversize list item, wide table row, chart, long heading prefix), **concurrent PDF ingestion corrupting text/tables** (lock added), NaN/inf/zero vectors accepted, filter-operator injection, invisible-only text becoming chunks, stale `parent_chunk_id` after re-ingestion, parent-id collision across users, unbreakable tokens, invalid Chroma collection names, lone surrogates crashing hashing, query-dimension not validated, repeated embeddings, DOCX/PPTX text bypassing normalisation. Incident: a patch script truncated `cleaners.py` to zero bytes; restored in full and re-verified (patch scripts now encode before opening a file for write).

### Real-document validation (all of `data/uploads/`, full stack: BGE + persistent Chroma + SQLite)

| File | Unit | Blocks | Chunks | Parents | Embedded | Tables | OCR images |
|---|---|---|---|---|---|---|---|
| 1-Introduction to Aspect-Oriented Software Systems.pdf | 35 pp | 243 | 52 | 26 | 52 | 1 | 18 |
| 2-Concepts of Aspect-Oriented Software Development.pdf | 36 pp | 347 | 47 | 38 | 47 | 0 | 12 |
| Intellistudy_final_proposal.pdf | 22 pp | 269 | 55 | 44 | 55 | 10 | 0 |
| Section 03 - Classical Encryption Techniques II.pptx | 21 slides | 149 | 41 | 20 | 41 | 19 | 1 |
| test.pdf (scanned page) | 1 | 8 | 3 | 3 | 3 | 0 | 0 (page OCR 0.949) |
| test1word.docx | 1 | 3 | 3 | 1 | 3 | 0 | 1 |
| test2.pdf (text + table + OCR image) | 1 | 3 | 3 | 1 | 3 | 1 | 1 (0.948) |
| test2word.docx, testword3.docx | 0-byte files | fail cleanly with `DocxParseError` | | | | | |

Zero validator problems and zero oversize chunks on every file. No hidden slides or charts exist in the real material, so those features are verified only by synthetic tests.

Findings: ~24 real queries checked by hand; top hits were correct for most (e.g. "What is separation of concerns?" -> p. 16 at 0.85; "What is a join point?" -> p. 17 at 0.85; "Who are the team members?" -> table at 0.64; "What is IntelliStudy?" -> OCR image chunk at 0.80), with correct citations, heading paths and OCR confidence propagation. Two real ingestion defects were found and fixed: (1) run-in bullet paragraph read as headings in `test2.pdf`; (2) PPTX slide-number placeholders ingested as content (12 junk chunks). Weaknesses are listed in section 7.

---

## 7. Known Issues

Retrieval quality
- **Table retrieval is weak**: "What is the academic year?" ranked the OCR paragraph (0.62) above the table holding the answer (0.60). Tables are embedded as `Column: value`; raw questions match worse than expected.
- **Retrieval threshold not calibrated**: an unrelated query ("How do I bake a chocolate cake?") scores about 0.49, close to real matches (0.52). No `min_score` default exists; the answer layer must calibrate one or re-rank.
- No labelled evaluation set (query -> expected citation) yet.

Ingestion
- **Table extraction**: merged cells in PDF tables leave empty spacer columns and a misaligned header (test2.pdf); several people in one cell are not split.
- `ocr_pages` statistic counts pages where OCR was attempted, not where it produced text (PPTX reported 11 with 1 useful image) - misleading.
- Scanned pages: no header/footer removal; heading detection is heuristic. Two-column PDFs and code panels are read top-to-bottom. Chart values, SmartArt/OLE, DOCX headers/footers/footnotes/text boxes are not extracted. Equations are plain text.
- **Arabic extraction limitation**: PyMuPDF returns Arabic in visual (reversed) order (expected-failure test); OCR is English-only; BGE-small is English-only; no language detection or RTL handling.
- One PPTX slide (21) ends up with no content blocks after the placeholder fix; not inspected.

Platform
- **Upload limits missing**: no file-size, page/slide-count, image-count, zip-bomb guard or Tesseract timeout.
- **PostgreSQL persistence missing**: users, courses, documents and parent chunks live in SQLite/Chroma files only.
- **CI/CD missing**: no GitHub Actions, no Dockerfile (docker-compose.yml is empty), requirements unpinned, Tesseract not in any image.
- Backend is a skeleton (`GET /` only): no upload API, auth or job queue. Chroma is single-process.
- Nothing is committed; `ruff format` not applied; `docs` not under review.

---

## 8. Roadmap

### Completed
1. PDF, PPTX, DOCX text extraction (OCR, tables, canonical schema, normalisation)
2. Chunking (hierarchical, parent-child, validated)
3. Embedding generation (BgeEmbedder)
4. ChromaDB integration (+ SQLite parent store)
5. Semantic retrieval (scoped, citations, parent expansion)
6. Re-ingestion system
7. Validation phase and real-document pass (586 tests, Ruff, MyPy, 93% coverage)

### In progress
- Fixing findings of the real-document pass (table embedding/retrieval quality, threshold calibration, table spacer columns).
- Housekeeping: commit the work, keep this file current.

### Planned
8. **RAG Answer Layer** (section 9)
9. Summarization
10. Citation-aware QA over the UI
11. Quiz generation
12. Adaptive learning engine, weak-topic detection, mastery estimation
13. Personalized exam generation, study recommendations
14. FastAPI backend (upload, jobs, auth) + PostgreSQL
15. React frontend
16. Docker/CI, upload limits, observability
17. Gemma 3 27B migration; Arabic support

---

## 9. Next Milestone: RAG Answer Layer

Goal: turn `RetrievalResult` into grounded, cited, refusable answers, independent of the LLM vendor.

| Component | Responsibility |
|---|---|
| **LLM Adapter** | `LLMClient` protocol (`generate(messages, params) -> text, usage`); OpenAI implementation first, Gemma later; timeouts, retries, token accounting, deterministic low temperature. |
| **Context Builder** | Selects hits and parents under a token budget; de-duplicates overlapping parents; orders by relevance and document order; assigns stable source tags `[S1]..[Sn]` mapped to `citation_label`s; marks low-confidence OCR sources. |
| **Prompt Builder** | System prompt (answer only from sources, cite every claim, say when unknown), context block, question, output format; keeps templates versioned and testable. |
| **Citation Injection** | Parses `[S#]` tags in the answer, validates each against supplied sources, replaces with `citation_label` (file, page/slide, heading path), drops or flags unsupported tags. |
| **Refusal Logic** | Refuses when no hit passes the calibrated threshold, when sources do not cover the question, or the top sources are all low-confidence OCR; returns a structured refusal with the closest sources. |
| **Hallucination Prevention** | Retrieval threshold + re-rank, context-only prompting, citation validation, optional answer-support check (each sentence must map to a source), numeric/quoted-text verification, evaluation set of answerable/unanswerable questions. |
| **Answer Service** | Orchestrates retrieve -> build context -> prompt -> LLM -> validate citations -> `Answer(text, citations, refused, sources, usage)`; scope-checked per user/course; logging for evaluation. |

Prerequisites: calibrated score threshold or re-ranker, labelled evaluation set, improved table retrieval (known issues above).

---

## 10. Production Readiness

**Ready**
- Ingestion of PDF/DOCX/PPTX into the canonical schema; chunking; embedding; vector indexing; scoped retrieval; re-ingestion; citations and OCR-confidence propagation. Backed by 586 tests, Ruff, MyPy, 93% coverage and a real-document pass.
- Concurrency of PDF ingestion (lock) and hostile-input handling (surrogates, invisible text, bad ids, NaN vectors, filter injection).

**Partially ready**
- **Retrieval quality**: good for prose and slides, weak for tables, no calibrated refusal threshold.
- **Table extraction** (merged cells), **scanned documents** (heuristic headings), **OCR statistics**.
- **Storage**: Chroma + SQLite work, but are single-process and not backed by PostgreSQL; tombstone retention is a policy, not yet a scheduled job.
- **Observability**: logging exists in modules; no metrics or tracing.

**Not ready**
- **RAG answer layer, LLM integration, quizzes, adaptive learning** (not started).
- **Backend API, auth, multi-user data model, frontend** (skeleton or empty).
- **Upload limits and abuse protection**, **Docker/deployment**, **CI/CD**, **dependency pinning**.
- **Arabic / multilingual** content.
- **Version control hygiene**: no commits of this work.

Verdict: the data and retrieval foundation is ready to build the RAG answer layer on, provided the answer layer owns threshold calibration and refusal; the system as a whole is not production-ready.

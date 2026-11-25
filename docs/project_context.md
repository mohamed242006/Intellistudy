# IntelliStudy - Project Context (single source of truth)

**IntelliStudy: AI-Powered Lecture Summarization and Adaptive Exam Generation System using Retrieval-Augmented Generation (RAG)**
Graduation project, Computer Engineering, Ain Shams University, team of four.

> **How to use this file.** It describes what exists in the repository today, why it was built that way,
> how it was validated, and what is still open. Read sections 2-5 before touching `ai/`.
> Assumed reader: an engineer or an AI assistant continuing the work with no other context.
> Last updated: 2026-11-25 (backend M0-M4 done and approved, M4.1 quality patch, M5 release gate drafted; earlier
> passes: future-work register, DeepSeek evaluation, move to Linux, equation-extraction investigation; see 13). Commit state:
> commit `1660115` holds ingestion, chunking, embedding, Chroma, the SQLite parent store and the base retrieval service;
> commit `1a38fad` ("Answering+ eval pt1") holds everything added up to 2026-11-15 (answer layer, retrieval add-ons,
> figure modules, `evaluation/`, `docs/`). Everything since (lock file, post-evaluation fixes, security contract, backend
> M0-M3) is on branch `post-eval-quality`, pushed, CI green. `evaluation/results/` is git-ignored and exists only locally (restored by hand after the machine move).
>
> **Labels used for status.** *Measured* = a number produced by a command on this repository (the date says when).
> *Decision (open)* = a choice nobody has made yet. *Hypothesis* = an expectation not yet measured. *Superseded* =
> historical information kept for context; the current value is stated next to it.

Related documents in `docs/`: `chunking_design_spec.md` (original chunking rules; ids, kinds and thresholds superseded by 3.2),
`chunking_architecture.md` (chunking code as first built), `embedding_retrieval_architecture.md`, `validation_progress.md`
(validation log, closed 2026-10-18), `e2e_validation_report.md` (30-file run), `multimodal_ingestion_design.md` (figure design),
`phase0_report.md` (E2E-07, E2E-10, figure Phase 0), `answer_layer.md` (answer layer MVP, E2E-08), `real_model_eval_plan.md` /
`real_model_eval_report.md` (Qwen2.5-3B evaluation), `figma_ui_context.md` (UI source of truth),
`backend_security_contract.md` (authoritative backend security reference, 2026-11-24), `SECURITY_MERGE_GATE.md` (M1/M2 gates), `M3_RELEASE_GATE.md` (M3 gate), `IntelliStudy_Architecture_Design_v1.1.docx`
(architecture design, Word). The four design documents named first carry a "superseded in part" banner listing what changed.

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
Frontend React + Tailwind (not started; `figma_ui_context.md` recommends React + TypeScript) · Backend Python/FastAPI (M0 foundation done 2026-11-24; product endpoints M1-M5) · AI: sentence-transformers, ChromaDB, RAG ·
DB: PostgreSQL planned (SQLite used now for parent chunks) · Documents: PyMuPDF, python-docx, python-pptx, pdfplumber, Pillow,
Tesseract/pytesseract · Optional speech: Whisper · Deployment: Docker/Compose (not started) · VCS/CI: Git/GitHub Actions (CI not started).

### LLM strategy
Phase 1 OpenAI API; Phase 2 self-hosted Gemma 3 27B. The architecture stays model-agnostic (an adapter interface) so the swap is small.
Two real models have been evaluated through the unchanged adapter (section 11): Qwen2.5-3B through local Ollama (2026-10, a floor
for the stack) and DeepSeek `deepseek-chat`, served as `deepseek-flash` in non-thinking mode (2026-11-23, hosted API). Neither is the
planned production model.

---

## 2. Current Architecture

```
Document (PDF / DOCX / PPTX)
  -> Ingestion          ai/ingestion      readers + OCR + table extraction + normalisation + figure detection/selection
  -> Canonical Blocks   Document / PageContent / Block / FigureData / SourceInfo (schema 2.1)
  -> Chunking           ai/chunking       sections -> child chunks (indexed) + parent chunks (context)
  -> Embeddings         ai/embedding      BgeEmbedder, BAAI/bge-small-en-v1.5, children only
  -> ChromaDB           ai/vectorstore    one collection per model + chunker major version; parents in SQLite (ai/storage)
  -> Retrieval          ai/retrieval      scoped search -> child hits (best first) + parent expansion + citations
                                          (+ bibliography demotion, optional reranker, relevance assessment)
  -> Answer Layer       ai/answering      context -> prompt -> LLM -> citations -> grounding -> cited answer or refusal
```

Single entry points:

```python
doc    = IngestionPipeline().ingest("lecture.pdf")                       # ai.ingestion.ingestion_pipeline
chunks = ChunkingEngine(tokenizer=default_token_counter()).run(doc, ChunkContext(user_id, course_id, document_uid, EMBEDDING_MODEL))
IndexingService(BgeEmbedder(), ChromaVectorStore(path=...), parent_store=SQLiteParentStore(...)).index(chunks.children, document_uid=uid, parents=chunks.parents)
result = RetrievalService(embedder, store, parent_store).search("query", user_id=..., course_id=..., k=5)
answer = AnswerService(retrieval_service, OpenAICompatibleClient("model")).answer("question", user_id=..., course_id=...)
```

Design principles: one canonical schema for all formats; additive/contract-driven layers; warnings never raise (confidence is the
degradation signal); every chunk carries enough metadata to cite itself; user and course scope is mandatory on every query;
re-ingestion is idempotent and reuses vectors.

---

## 3. Implemented Components

Status legend: DONE = implemented and tested.

### 3.1 Ingestion (`ai/ingestion/`)

**Canonical schema (DONE)** - `models.py`, `structure.py`. Schema version "2.1" (2.0 plus the additive figure fields of 3.8).
- `Document`: `source: SourceInfo` (doc_id = sha256[:16], sha256, file_name, file_type, size, unit page|slide|document, page_count, parser, ingested_at, title, author, created, modified, language), `metadata`, canonical `statistics`, `pages`.
- `PageContent` (page / slide / always 1 for DOCX): text, ocr_text, final_text, tables, images, figures, size, confidence 0-1, page_type, warnings, blocks.
- `Block` (the unit chunkers use): type (heading | paragraph | list_item | table | image_ocr | chart | notes | figure), text, page_number, global `order`, `level`, `heading_path` (ancestor titles; a heading's own path ends with itself), `list_marker`, `ref_index`, `bbox`, `confidence`.
- Canonical statistics (same keys for every format): page_count, unit, block_count, heading_count, list_item_count, table_count, image_count, image_ocr_count, chart_count, total_characters, average_confidence, low_confidence_pages (<0.6), warning_count.
- Citation label from `structure.citation_label`: `p. 4 > Caching > LRU`, `slide 4 > ...`, or the heading path for DOCX.
- Why: before this, each reader returned flat text with ad-hoc markers and different metadata; every downstream module would have special-cased formats.

**PDF Reader (DONE)** - `pdf_reader.py`. PyMuPDF text layer; whole-page OCR only when there is no text layer, per-image OCR otherwise. Features, each added because of a real defect in the sample lectures:
- visual-row merging; bullet detection (glyph spans, `o Item`, `- Item`, private-use glyphs) with wrapped-bullet re-joining and nesting depth;
- headings: size >= 1.15 x body or bold single row, <=100 chars, not ending `.,;`; wrapped headings merged; levels from a document-wide `LayoutProfile` (a size must recur on >= 2 pages except in 1-2 page documents); PDF bookmarks override levels;
- text containing inline bullet glyphs, or in a block of 4+ rows, is never a heading (fixed a run-in bullet paragraph in `test2.pdf` being read as two headings);
- running header/footer removal (top/bottom 18% of the page, repeated on >= max(3, 50%) of pages); TOC rows dropped; repeated logo/banner image OCR blanked.

**DOCX Reader (DONE)** - `docs_reader.py`. One logical page, cite by heading path. Body walked once in original order (tables and image OCR appear where they are in the document), `Title` = level 0 and `Heading N` = N, numbering definitions resolved (bullet vs decimal/letter/roman, counters restart), tables rendered key/value with merged cells collapsed, images de-duplicated and OCR'd at the paragraph that references them. Not extracted: headers/footers, footnotes, text boxes.

**PPTX Reader (DONE)** - `pptx_reader.py`. One page per slide; reading order by (top bucket, left), groups expanded; title (also inside groups) emitted once as level-1 heading; bullets/numbering rendered; charts (title, axes, categories, series, legend, type, and the plotted values since Phase 0); tables with merge handling; images OCR'd with a per-file sha1 cache; EMF/WMF that cannot be decoded are a mild skip (0.70) not a failure; hidden slides kept and flagged; speaker notes become a `notes` block. Slide-number, footer and date placeholders are skipped (they produced junk chunks such as "6").

**OCR (DONE)** - `ocr_processor.py` (Tesseract wrapper, filters for tiny/thin/no-text/low-confidence images, per-document cache) and shared `image_ocr.py` (decode, score, confidence). Image scores: OCR success 0.85-1.0 scaled by engine confidence; intentional skip 0.60-0.85; unsupported format 0.70; error 0.0; page/slide confidence = mean of items, 1.0 when none. English only (`lang="eng"`).

**Table Extraction (DONE)** - `table_extractor.py`: pdfplumber tables for PDF (text re-read excluding table boxes); DOCX and PPTX read tables natively. Rendering as pipe text (default) or key/value.

**Document Builder (DONE)** - `document_builder.py`: finalises PDF pages into blocks, computes confidence (`ConfidenceScorer`) and page type (TEXT/SCANNED/TABLE/MIXED).

**Text normalisation (DONE)** - `cleaners.py`: selective NFKC (keeps superscripts/subscripts, fractions, double-struck sets so STEM text survives), hyphen repair that keeps real compounds, removal of invisible/bidi characters and lone surrogates; applied to PDF, DOCX and PPTX.

**Pipeline (DONE)** - `ingestion_pipeline.py`: routing by extension or MIME type, injectable readers, `IngestionError` family (`PDFParseError`, `DocxParseError`, `PptxParseError`); a failing page/slide becomes an empty page with confidence 0 and a warning. PDF ingestion is serialised with a lock because the PDF layers keep per-document state.

**Figures (Phase 0, DONE)** - `figures.py`, `figure_selection.py`; see 3.8. Schema 2.1 adds `BlockType.FIGURE`, `FigureData`, `PageContent.figures/size`.

**E2E-07 (DONE)**: a PPTX slide without a title placeholder gets its title from the text box with the clearly largest explicit font size (conservative: ties and ambiguous cases stay untitled). 3 decks went from 0 to 11 / 15 / 3 headings.

### 3.2 Chunking and parent-child chunking (`ai/chunking/`) - DONE

`ChunkingEngine` = `BlockSelector` -> `build_sections` -> `ChunkBuilder` (`AtomBuilder`, `TextSplitter`) -> `ParentBuilder` -> `ChunkValidator`.

- **Child chunks** (`ChildChunk`) are the only indexed unit. Config: target 400 tokens, hard max 480, overlap 60, heading-prefix cap 60, minimum 80 (small neighbours merge), parent max 1600.
- **Parent chunks** (`ParentChunk`) group children of one section; used only as expansion context at retrieval, never embedded.
- **Atoms** (never split across chunks unless over the hard limit): tables (header repeated on table parts), notes, charts, figures (clipped to fit, never split). Over-limit list items / wide rows / charts are split by hard-limit rules; unbreakable tokens split by characters.
- **Slides** never cross a slide boundary; title-only slides (< 6 body tokens, no rich content) are not indexed; hidden slides are excluded.
- **OCR**: image_ocr confidence < 0.3 dropped, < 0.6 kept and flagged `low_confidence`.
- Each chunk carries: ids, `heading_path`, `citation_label`, page/slide range, block ranges and types, kind (text | table | image_ocr | notes | figure | mixed), source kind, OCR confidence, token count, `embedding_text` (heading prefix + body; tables rendered `Column: value`), `embedding_hash`, `record_hash`, parent link.
- Chunker version **1.3.0** (1.1.0: merged small sections keep their titles in the text; 1.2.0: figure chunks; 1.3.0: **stable ids**). Chunk ids are `c-{hash12 of the chunk's own text}` (`.{n}` for repeated identical text) and parent ids `p-{hash12}`: independent of position and of the file hash, so editing a file leaves untouched chunks with the same id and vector (E2E-08; 98% / 68% / 77% of ids survived on three real edits). The collection name uses the major version only.
- Token counting: real BGE tokenizer (`HFTokenCounter`) or approximate counter fallback.

### 3.3 Embeddings and BGE Embedder (`ai/embedding/`) - DONE
`BgeEmbedder`: BAAI/bge-small-en-v1.5 (384-d), lazy model load, documents embedded plain, queries with the BGE retrieval instruction, vectors L2-normalised, NaN/inf/zero vectors rejected, identical texts embedded once per call. `Embedder` is a protocol so other models can be swapped in.

### 3.4 ChromaDB integration and storage (`ai/vectorstore/`, `ai/storage/`) - DONE
- `ChromaVectorStore`: persistent client, **one collection per embedding model + chunker major version** (`chunks__bge-small-en-v1.5__c1`, names sanitised with hash suffix), cosine space, children only, metadata = citation/scope/kind/OCR fields, `vector_id = {document_uid}:{chunk_id}`.
- Mandatory `user_id` + `course_id` scope on every query; filter validation (no operators in values, reserved keys protected).
- `SQLiteParentStore`: parent chunks keyed `document_uid:parent_chunk_id` (no collision between users uploading the same file). PostgreSQL planned.
- `InMemoryVectorStore` / `InMemoryParentStore` (`memory_store.py`) for tests.

### 3.5 Retrieval Service (`ai/retrieval/`) - DONE
`RetrievalService.search(query, user_id, course_id, k, document_uids, filters, min_score, include_low_confidence, expand_parents, parent_token_budget)` returns `RetrievalResult(hits, parents, warnings, assessment)`. Children are searched first; parents are attached as expansion context under a token budget; query-vector dimension is validated; each `RetrievedChunk` exposes text (never the embedding text), score, kind, citation_label, heading_path, page/slide, OCR confidence and low-confidence flag.

**E2E-10 additions (DONE, measured)** - `references.py`, `rerank.py`, `assessment.py`, `calibration.py`:
- bibliography chunks are ranked after body text unless the query asks about authors/citations/sources (`include_references`);
- optional cross-encoder reranking (`CrossEncoderReranker`, `cross-encoder/ms-marco-MiniLM-L-6-v2`; about 2.5 s/query on CPU with 20 candidates);
- `result.assessment` = strong / weak / none advice from vector score, reranker score, margin and lexical coverage, plus `missing_terms` (question words found nowhere in the hits). The thresholds are a versioned policy calibrated on 87 labelled queries and bound to the embedder and reranker they were measured with; with other models the service says so instead of applying them. Detail and numbers: [`phase0_report.md`](phase0_report.md) section 2.

### 3.6 Re-Ingestion System (`ai/chunking/indexing.py`) - DONE
`IndexingService` + `ReingestPlanner`: embed -> upsert parents -> upsert children -> delete stale. Per chunk the planner decides **unchanged** (same ids and hashes), **refreshed** (metadata changed: `record_hash`), **reused** (same `embedding_hash`, vector copied, no re-embed) or **embedded**. Re-ingesting an unchanged file is a no-op (0.27 s for 3000 chunks); stale chunks are deleted. Tombstone retention decision: 7 days (policy recorded; deletion currently immediate in the stores).

### 3.7 Validation infrastructure - DONE
See section 6. unittest suites, random-document generator, PDF/PPTX fixtures, performance budgets, Ruff/MyPy/coverage configuration in `pyproject.toml`.

### 3.8 Figure infrastructure, Phase 0 (no Vision LLM) - DONE
Plan and rationale: [`multimodal_ingestion_design.md`](multimodal_ingestion_design.md). Results: [`phase0_report.md`](phase0_report.md).
- **Detection**: PDF raster pictures and vector charts/diagrams (clustered drawing operators; labels around the cluster become `inner_text`); PPTX pictures; DOCX inline pictures. Captions ("Figure 3: ...", punctuation or bold label required) are paired with the nearest graphic; a caption without a graphic is kept as a caption-only figure.
- **FigureData / FIGURE block**: caption, inner text, OCR text, alt text, citing sentences (`mentions`), selection score and reasons, and an empty `description` reserved for a later model. Source text and generated text are never mixed.
- **Image Selection Layer**: hard rules (tiny, banner, small repeated picture, later copy of a large repeated picture), caption keeps, otherwise a small logistic model over pixel/layout/text statistics (+ bonuses for a citation in the text and alt text). Every decision is traced with reasons in `metadata["figures"]["decisions"]`.
- **Chunking and citations**: one isolated `figure` chunk per kept figure with a fixed template (`[Figure 3] (page 7)`, caption, text in figure, up to two citing sentences); citation label `p. 7 > section > Figure 3`; metadata `figure_id`, `figure_label`, `figure_type`, `figure_kind`.
- **Side fixes**: chart gridlines read as a phantom table no longer hide the figure and are removed; PPTX chart blocks now include the plotted numbers.
- **Real-corpus reach** (*measured* 2026-11-15, section 6 "Corpus coverage assessment"): lecture figures have almost no captions or citing sentences, so they reach the index mainly through OCR and vector inner text; Phase 0 is insufficient for 2 of the 30 evaluation files and partial for 2.

### 3.9 Evaluation harnesses (`evaluation/`)
Not imported by product code. Retrieval: `retrieval_dataset.py` (87 labelled queries), `index_builder.py`, `retrieval_eval.py` (strategies, calibration, shipped-policy report). Answers: `answer_eval.py` (extractive baseline and quick runs), `answer_gold.py` (111 cases with gold facts and gold sources; post-evaluation corrections listed in its docstring), `answer_metrics.py` (correctness, citation hit/precision/coverage, NLI faithfulness and per-sentence attribution, hallucination, refusal metrics with Wilson intervals), `real_model_eval.py` (stages: `retrieve` (cache), `answer` (records raw replies; stops at the first `llm_unavailable` with the provider's error body, evaluation-only), `score`, `replay` (offline policy re-scoring), `label-template`), `policy_replay.py` (offline grounding policies A / B1 (experimental) / C), `root_cause.py` (failure triage), `handlabel/` (hand-label template of the 119 run-B sentences for judge validation, with instructions; **not labelled**). Raw outputs in `results/` (git-ignored; the Qwen runs and their retrieval cache are kept in `results/runs_2026-10/` with `SHA256SUMS.txt`). Figures: `figure_benchmark/` (hand labels for 236 real figure candidates, contact-sheet tools, synthetic corpus with exact ground truth, detection and retrieval runners).

### 3.10 Answer Layer MVP (`ai/answering/`) - DONE; evaluated on two real models (Qwen2.5-3B: criteria not met; DeepSeek flash: all non-NLI criteria met, NLI-judged criteria fail on an unvalidated judge; see 11)
Details, guarantees and results: [`answer_layer.md`](answer_layer.md) (MVP record) and section 11 (real-model evaluation).
- `llm.py` LLM adapter (`LLMClient` protocol; `OpenAICompatibleClient` over stdlib HTTP for OpenAI / vLLM / Ollama / self-hosted Gemma or Qwen; `ExtractiveLLM` no-model baseline; `ScriptedLLM` for tests); `context.py` Context Builder (numbered sources S1..Sn, budget, de-duplication, wider-section context, generated/low-confidence flags); `prompt.py` Prompt Builder (versioned `answer-1`, fenced sources, neutralised tags); `citations.py` Citation Injection (validated `[S#]` -> reader-facing `[n]`); `grounding.py` Hallucination Prevention (per-sentence citation, word, number and quotation support; failing sentences removed); `refusal.py` Refusal Logic (pre-model and post-model, reasons `no_results`, `not_relevant`, `model_declined`, `uncited_answer`, `unsupported_claims`, `llm_unavailable`); `service.py` Answer Service.
- Guarantees: retrieval scoped to one user and course; no uncited or ungrounded answer is returned; unrelated questions are refused before the model is called; a model outage is a refusal; source text cannot close its fence or impersonate a citation; answers resting on AI-generated figure text are flagged.
- Production grounding policy: **A** (the shipped default above: uncited or unsupported sentences are removed). It stays the default until the stronger-model comparison is done (section 9). Alternative policies B1 and C exist only in the offline evaluation harness (3.9).
- Measured with the extractive baseline on 87 labelled queries (2026-10-19): 24/24 unrelated refused before any model call; near-miss 9/10 refused; answerable 45/53 answered, 37/53 citing the expected source. This evaluates the machinery, not a language model's writing.
- Measured with a real model (2026-10-25, Qwen2.5-3B, 111 cases): refusal and attribution hold; correctness fails its criterion. Summary in section 11.
- Measured with a second real model (2026-11-23, DeepSeek flash, same 111 cases and identical retrieval): correctness 68/72 = 0.94, no wrong answer among 68 answered, refusal recall 37/37, false refusal 4/72. Summary in section 11.2.

### 3.11 FigureDescriber plug-in point (`ai/ingestion/figure_description.py`) - DONE (no vision model included)
`FigureDescriber` / `FigureCropper` protocols, `PdfFigureCropper`, `enrich_figures` (never overwrites source text; rejects descriptions whose numbers are not in the author's text; caches by image hash + model + prompt version; one failing figure never stops the rest), `NullFigureDescriber`, `StubFigureDescriber`. The chunker renders a described figure with a labelled generated-description line, and because ids depend on text only, enrichment renames only the figure chunks. A real describer (Qwen2.5-VL or other) is adopted only if it clearly beats the Phase 0 baseline on the figure benchmark and on real figure-heavy documents. PPTX/DOCX croppers do not exist yet.

### 3.12 Backend foundation, M0 (`backend/`) - DONE 2026-11-24
Vertical-slice milestone M0 of the Backend Vertical Slice; security rules from [`backend_security_contract.md`](backend_security_contract.md). Details and run instructions: `backend/README.md`.
- `create_app()` factory (no module-level app); pydantic-settings from `INTELLISTUDY_*` environment variables only, secrets as `SecretStr`; `demo`/`prod` refuse to start without a JWT secret of at least 32 bytes (placeholders and low-variety values rejected), `prod` also without the selected provider's key; approved CORS allowlist (`localhost:3000`, `localhost:5173`, `127.0.0.1:5173`), wildcards rejected.
- Pure-ASGI middleware: request ids, security headers (`nosniff`, `no-referrer`, `DENY`, CSP, `Cache-Control: no-store` on the API), body-size limit that also catches chunked bodies, and an innermost unhandled-error middleware so a 500 keeps CORS, security headers and the request id (a Starlette catch-all handler would have dropped them; found by the M0 tests). Errors are RFC 7807 problem documents without traces; validation errors never echo submitted values; unknown routes return the standard 404 (OWN-04 shape).
- JSON logging with secret redaction (known values plus credential shapes) and a security event log; in-memory sliding-window rate limiter with the contract's default limits (attached to routes from M1).
- SQLAlchemy 2 + Alembic (baseline revision; `python -m backend.app.db.migrate`): portable UUID-string ids, UTC-aware datetimes, naming convention; SQLite with WAL, foreign keys and busy timeout. PostgreSQL needs only `INTELLISTUDY_DATABASE_URL`.
- LLM providers behind one interface that also satisfies `ai.answering.llm.LLMClient`: `DeepSeekProvider` (default `deepseek-chat`, the validated configuration; other DeepSeek models get `thinking: disabled`), `OpenAIProvider` (`max_completion_tokens` and no `temperature` for reasoning models), `LocalProvider` (= `FutureLocalProvider`; Ollama/vLLM); no redirects followed, retries with jitter on 408/409/429/5xx, provider error bodies redacted in logs and never returned.
- `AIContainer`: lazy embedder, reranker, Chroma store, parent store and retrieval service; the only backend module allowed to touch the stores (static test). `GET /api/v1/health` reports booleans and names only.
- Tests: 74 in `backend/tests` (config and secrets, HTTP hardening, provider contracts, redaction, rate limits, database, static architecture rules for VEC-03/VEC-04/OWN-03/SEC-02). CI workflow `.github/workflows/backend.yml` (gitleaks on full history, pip-audit with recorded exceptions, ruff, mypy, both test suites) and `.pre-commit-config.yaml` + `.gitleaks.toml` added; CI ran green on GitHub (run 1, commit `7892321`).
- Dependency audit (2026-11-24): Pillow 12.3.0 -> 13.0.0 (42 advisories, several in decoders reachable from images inside uploads) and setuptools -> 84.2.1; the 800-test `ai/` suite passes on Pillow 13. chromadb 1.5.9 has 4 server-mode advisories with no fix; recorded as an exception (contract Appendix C) because the embedded client is used; running Chroma as a server is blocked until they are fixed.

### 3.13 Backend identity, courses and ownership, M1 (`backend/`) - DONE 2026-11-24 (CI run #2 green)
Release gate: [`SECURITY_MERGE_GATE.md`](SECURITY_MERGE_GATE.md), 79 items; all pass locally (evidence table in the gate).
- Endpoints: `/api/v1/auth/{register, login, refresh, logout, logout-all, me, change-password}`, `/api/v1/courses` (create, list) and `/api/v1/courses/{id}` (get, patch: rename / archive, delete). Migration `0002_users_tokens_courses` (users, refresh_tokens, courses; `courses.owner_id` non-nullable FK).
- Passwords: Argon2id (default m=64 MiB, t=3, p=1; contract floor m=19 MiB, t=2), rehash on login when parameters change, policy 10-128 chars with a letter and a digit and not a common password; e-mails unique case-insensitively; a dummy Argon2 verification for unknown e-mails so login timing does not reveal accounts.
- Access tokens: HS256 only, required `sub iss aud iat exp jti typ`, 15 minutes, checked against the application clock with 30 s leeway; sub-second `iat`, so `tokens_valid_after` (set by logout-all and password change) revokes exactly; accepted only from one `Authorization: Bearer` header; one generic 401.
- Refresh tokens: 256-bit opaque values, SHA-256 stored, `__Secure-` cookie scoped to `/api/v1/auth`; rotation claims the row with a conditional UPDATE so concurrent refreshes cannot both win; reuse revokes the family; 7-day idle and 30-day absolute lifetime; refresh and logout require `X-Requested-With: IntelliStudy` and an allowed Origin (CSRF).
- Lockout 15 min after 5 consecutive failures (also wrong current passwords in change-password), indistinguishable from a wrong password; rate limits on login (per IP and per account), register (per IP) and refresh (per user).
- Ownership: `services/ownership.get_owned` is the single choke point (canonical-UUID check, id **and** owner in one query, identical 404 for missing / foreign / malformed ids, security event only for foreign ids); list queries filter by owner; request models forbid unknown fields; the ADMIN role grants no course access.
- Tests: 80 gate tests (`backend/tests/test_g1_*.py`, one per gate item plus a traceability test) using a fake clock, real migrations and per-user clients; 154 backend tests in total. New dependencies argon2-cffi 25.1.0 and PyJWT 2.15.1 (lock updated, pip-audit clean apart from the recorded exceptions).
- Not in M1 (contract SHOULDs, later): JWT key rotation with `kid` (JWT-08), purge job for expired refresh tokens (RT-09), e-mail verification and password reset (FR-AUTH-03/06).

### 3.14 Backend documents and processing, M2 (`backend/`) - DONE 2026-11-24 (CI run #3 green)
Gate: [`SECURITY_MERGE_GATE.md`](SECURITY_MERGE_GATE.md), M2 section, 39 items passing locally; findings F-M2-01..14 in
[`backend_security_contract.md`](backend_security_contract.md) Appendix D (contract v1.1: UPL-06, UPL-08, UPL-12 updated).
- Endpoints: `POST/GET /api/v1/courses/{id}/documents` (streaming multipart upload of 1-10 files; list), `GET /api/v1/documents/{id}` (status, progress, page/chunk counts, fixed error code + sentence), `GET /api/v1/documents/{id}/file` (attachment download), `POST /api/v1/documents/{id}/retry`, `DELETE /api/v1/documents/{id}`; course deletion now cascades through documents. Migration `0003_documents_jobs`.
- Upload: course ownership checked before any byte is stored; python-multipart callback parser writes each file to an exclusive 0600 file while counting and hashing, aborting at 100 MB (also for chunked bodies); extension + magic-byte agreement; 10 files per request, 1 GB quota, 20 files/hour, at most 5 active jobs per user; duplicates only within the same user and course.
- Storage: `{root}/{owner}/{document}/original.{ext}`, UUID components only, every path checked to stay inside the root, 0700/0600, atomic placement, stale partial uploads swept at startup; client file names are display-only (normalised, no control/bidi characters).
- Sandboxed parsing (`backend/app/worker/`): a child process (`python -m backend.app.worker.parse_child`) with an allowlisted environment (no secrets), `RLIMIT_AS`/`RLIMIT_CPU`/`RLIMIT_FSIZE`/no core dumps, Pillow bomb guard, 30 s Tesseract timeout; the parent enforces a 10-minute wall clock and a 2 GiB resident-memory watchdog over the process group. Preflight before any parser: ZIP inspection (500 MB uncompressed, ratio 100, 10,000 entries, traversal names, duplicate and overlapping entries, ZIP encryption), macros (`vbaProject.bin`, macro-enabled content types), encrypted OOXML (OLE `EncryptedPackage`) vs legacy formats, password-protected PDFs, page/slide limit (300). The child returns JSON only; the parent rebuilds chunks from an exact field set and checks each chunk's user, course and document ids.
- Jobs: `processing_jobs` table, one in-process runner thread, atomic claim by conditional UPDATE, re-load of the document with its owner at every stage, statuses queued -> extracting -> embedding -> indexing -> ready / failed / deleting with progress, one retry for infrastructure errors, partial index removed on failure, deletion during processing finished by the runner, interrupted jobs requeued at startup. Measured on the real stack (live run): AOP lecture 1 PDF -> ready (35 pages, 53 chunks), `SPE_l1.pptx` -> ready in 2.2 s (86 slides, 68 chunks), BGE + Chroma loaded lazily.
- `ai/` change: `OCRProcessor` has an opt-in per-call Tesseract timeout (default off; 800-test `ai/` suite unchanged).
- Tests: 39 M2 gate tests (`backend/tests/test_g2_*.py`, all generated fixtures incl. ZIP bomb, overlapping-entry ZIP, encrypted PDF/OOXML, macro DOCX, 900-megapixel PNG, hanging / memory-hungry / env-probing children); static rule against bidi control characters in sources (finding F-M2-08); 195 backend tests in total. New dependency python-multipart 0.0.34.
- **Release blocker F-M2-10 (declared 2026-11-24):** vectors exist before a document is `ready`. Enforced by `backend/app/services/retrieval.py` (the only path to `RetrievalService`; exact `status == ready` allowlist, `document_uids` on every query, post-search re-check, no store query for an empty scope); tests G3-RDY-01..07 pass and fail under a mutation check.

### 3.15 Backend grounded chat, M3 (`backend/`) - DONE and APPROVED 2026-11-24 (CI run #5 green; F-M2-10 closed)
Gate: [`M3_RELEASE_GATE.md`](M3_RELEASE_GATE.md), 52 items passing in CI (run #5, commit `f05bf8e`), evidence in its section 2.9, signed off in its section 3; findings F-M3-01..04 in
[`backend_security_contract.md`](backend_security_contract.md) Appendix D (contract v1.3).
- Endpoints: `POST/GET /api/v1/courses/{id}/conversations`, `GET/DELETE /api/v1/conversations/{id}` (detail includes the message history), `POST /api/v1/conversations/{id}/messages` (`question` 1-2000 characters, optional `document_ids` 1-100 to narrow the scope). Migration `0004_conversations_messages` (`conversations`, `messages`; both cascade from the course).
- Flow (`backend/app/services/chat.py`): owned conversation -> question normalised (NFC, control characters removed) -> chat rate limit (20/min) -> per-user daily token budget (429 before any provider call) -> scope resolved by the READY-only layer (3.14) -> unchanged `ai/answering` `AnswerService` over a `BoundRetrieval` that refuses any other user or course -> every citation re-checked against the scope, the document's `ready` status and the retrieved passage text (else refused `scope_violation`) -> answer text sanitised (markdown/HTML images removed) -> state -> stored message.
- States, precedence confirmed by the team: `refused` > `partial` > `low_confidence` > `answered`; refusal reasons `no_results`, `not_relevant`, `model_declined`, `uncited_answer`, `unsupported_claims`, `llm_unavailable`, `scope_violation`; each with a fixed notice and the nearest material.
- Provider failures (timeouts, 429/5xx after retries, 4xx, malformed or blank replies, redirects, no provider configured) become `refused` / `llm_unavailable` with status 201; provider error bodies and reasoning text are never returned, stored or logged.
- `ai/` change: `AnswerService` takes a `Retriever` protocol (typing only; behaviour unchanged).
- Token budget (fixed after approval, F-M3-05): read only from the usage ledger `llm_usage` (one row per provider call, linked only to the user; migration `0005_llm_usage`); deleting conversations, messages, documents or courses refunds nothing (`backend/tests/test_usage_ledger.py`, 9 tests).
- Tests: 52 M3 gate tests (`backend/tests/test_g3_*.py`) plus traceability; 248 backend tests at approval, 257 with the ledger tests. **Release blocker F-M2-10 closed** (contract v1.4). Not yet done: the optional manual DeepSeek smoke run.


### 3.16 Backend summaries and quizzes, M4 (`backend/`) - DONE and APPROVED 2026-11-25 (CI run #7 green on `c1ee771`)
Gate: [`M4_RELEASE_GATE.md`](M4_RELEASE_GATE.md) v1.2, 67 items passing locally, evidence in its sections 2.11-2.12; findings
F-M4-01..07 in [`backend_security_contract.md`](backend_security_contract.md) Appendix D (contract v1.9). Decisions D-1..D-5
approved without changes.
- Endpoints: `GET/POST /api/v1/documents/{id}/summary` (`{regenerate?}`; 200 stored, 202 queued), `POST/GET /api/v1/courses/{id}/quizzes` (`{document_ids?, question_count 5-30, question_types mcq|true_false, title?}`), `GET/DELETE /api/v1/quizzes/{id}`, `POST /api/v1/quizzes/{id}/regenerate`. Migration `0006_summaries_quizzes` (`summaries`, `quizzes`, `quiz_sources`, `quiz_questions`, `quiz_answer_keys`, `generation_jobs`).
- Generation runs on its own background thread (`GenerationRunner`; ingestion keeps its runner). Sources are read only through the scoped loader (`services/sources.py`: owned ready row -> parent keys -> `get_many(keys, user_id, course_id)`, tripwire on every parent). Every model call goes through the usage ledger with a budget check before each call; results are stored in one transaction only after the sources are re-read and still `ready`.
- Summaries (`services/summaries.py`): one structured summary per document; map batches cover every section exactly once (ordered merge, no gaps); tags parsed and grounding-checked as in chat; images stripped; headings from the document's structure; page/slide ranges from citations. Stored and served until an explicit regeneration, which replaces it atomically (a failed one keeps the old).
- Quizzes (`services/quizgen.py`): JSON output parsed strictly; deterministic validation (structure, evidence quoted from a supplied source, correct option covered by the evidence, no second covered option, tags from enums, near-duplicates removed); server-side balanced option shuffle; answer keys in their own table, never serialised (no API module imports it). Shortage: `ready` with at least 5 and a notice, else `failed` / `insufficient_material`.
- Deletion (`services/lifecycle.py`, called from the document purge): summaries deleted (T-1); quizzes with only that source deleted (T-2); multi-source quizzes `invalid` / `source_deleted` with questions and keys removed until regenerated (T-3). The token ledger is never touched.
- Tests: 67 M4 gate tests (`backend/tests/test_g4_*.py`) plus traceability; 325 backend tests in total.
- **M4.1 patch (2026-11-24)**, after the manual DeepSeek run on a real journal PDF (gate v1.2, section 2.12; contract v1.8):
  quiz evidence may quote a word the PDF split at a line end (F-M4-06: soft hyphens; it had dropped 10 of 22 questions,
  5 of 10 delivered); the sentence splitter no longer ends sentences at "U.S.", "Rev.", "Dr.", "Prof.", "etc." and
  summaries drop citation-number fragments (F-M4-05). Instrumented yield: 60% before, 80% and 100% after. Open:
  F-M4-07 (soft hyphens at ingestion split terms for grounding and retrieval). 15 regression tests; 340 backend tests.
---

## 4. Current Folder Structure

```
Intellistudy/
├── ai/
│   ├── ingestion/     models, structure, cleaners, image_ocr, ocr_processor, pdf_reader, table_extractor,
│   │                  document_builder, docs_reader, pptx_reader, ingestion_pipeline, figures, figure_selection,
│   │                  figure_description
│   ├── chunking/      config, tokens, ids, citation, render, models, text, selection, sections, atoms, builder,
│   │                  parents, validation, engine, interfaces, indexing, memory_store, errors
│   ├── embedding/     bge.py (BgeEmbedder)
│   ├── vectorstore/   chroma_store.py (ChromaVectorStore)
│   ├── storage/       sqlite_parent_store.py (SQLiteParentStore)
│   ├── retrieval/     models, service (RetrievalService), references, rerank, assessment, calibration
│   └── answering/     models, llm, context, prompt, citations, grounding, refusal, service (AnswerService)
├── backend/           (M0 3.12, M1 3.13, M2 3.14; see backend/README.md)
│   ├── app/           main.py (create_app), core/ (config, clock, passwords, tokens, logging, errors, middleware,
│   │                  ratelimit), db/, providers/ (DeepSeek, OpenAI, Local), services/ (auth, ownership, courses,
│   │                  ai_container), api/v1/ (health, auth, courses, schemas)
│   ├── migrations/    Alembic env + versions (0001-0003: baseline, users/tokens/courses, documents/jobs); alembic.ini
│   ├── tests/         195 unittest tests: M0, static rules, M1 gate (test_g1_*), M2 gate (test_g2_*)
│   └── requirements.txt   direct dependencies (ranges); exact pins in requirements.lock.txt
├── (frontend/)        does not exist yet
├── evaluation/        retrieval_dataset, index_builder, retrieval_eval, answer_eval, answer_gold, answer_metrics,
│                      real_model_eval, policy_replay, root_cause, handlabel/ (judge-validation template),
│                      figure_benchmark/ (labels, synthetic corpus, evaluators),
│                      results/ (git-ignored outputs; runs_2026-10/ = Qwen runs + retrieval cache + SHA256SUMS.txt;
│                      runs_2026-11/ = DeepSeek smoke, A run, B1/C replays and their metrics/cases/audit files)
├── tests/             38 files: 33 test modules + 5 support files (chunk_fixtures, pdf_fixtures, pptx_fixtures,
│                      random_docs, __init__)
├── data/uploads/      root: 2 Aspect-Oriented lecture PDFs, Intellistudy_final_proposal.pdf, Section 03 PPTX, test.pdf, test2.pdf;
│                      docs/ (10 DOCX), PDFs/ (10 PDF), pptx/ (10 PPTX)
├── docs/              this file; chunking_design_spec, chunking_architecture, embedding_retrieval_architecture (historical, bannered);
│                      validation_progress, e2e_validation_report, multimodal_ingestion_design, phase0_report, answer_layer (bannered),
│                      real_model_eval_plan, real_model_eval_report, figma_ui_context, IntelliStudy_Architecture_Design_v1.1.docx
├── pyproject.toml     ruff / mypy / coverage configuration
├── requirements.lock.txt  exact pins of the project .venv (121 packages, uv pip freeze, 2026-11-23)
├── docker-compose.yml EMPTY (no Dockerfile)
├── test_pptx_pipeline.py (10 routing tests), test_docs_pipeline.py, test_pipeline.py (manual dump scripts)
└── .gitignore
```

Environment (since 2026-11-23): Linux x86_64; project virtual environment `.venv` (git-ignored) with Python 3.12.16 (uv-managed;
the system Python is 3.14 and is not used); CPU PyTorch 2.15.0 (deliberately CPU, so NLI scoring stays comparable with the CPU-measured
Qwen numbers), transformers 5.24.0, sentence-transformers 6.0.0, chromadb 1.5.9, PyMuPDF 1.28.2, python-docx 1.2.0, python-pptx 1.0.2,
pdfplumber 0.11.10, Pillow 13.0.0 (12.3.0 until 2026-11-24, upgraded for security advisories), SQLAlchemy 2.1.9, Alembic 1.20.1, pytesseract 0.3.13 + Tesseract (`/usr/bin/tesseract`), ruff 0.17.1, mypy 2.4.0, coverage 7.16.2,
vulture 2.16; exact pins in `requirements.lock.txt` (recreate command in its header). pytest is not installed (tests use unittest).
Hugging Face models (BGE-small, MiniLM reranker, NLI judge) download on first use. *Superseded:* Windows 11 + Python 3.12 in a
OneDrive folder (until 2026-11-15).

---

## 5. Technical Decisions

| Decision | Choice | Why |
|---|---|---|
| Embedding model | **BAAI/bge-small-en-v1.5** | Small (384-d), fast on CPU, strong English retrieval; approved by the team. English-only, so Arabic needs a different model later. |
| Chunking | **Hierarchical (section -> child -> parent)**, structure-aware, 400/480/60 tokens | Headings give natural boundaries; hard limit keeps within BGE's 512-token window. |
| Retrieval | **Parent-child**: search small children, return parents as context | Small chunks match precisely; parents give the LLM surrounding context. Parents are never embedded. |
| Chunk IDs | **Stable, content-based** (chunker 1.3.0): `c-{hash12 of the chunk text}` (`.{n}` for repeated identical text), parents `p-{hash12}`; vector id `{document_uid}:{chunk_id}` | Unchanged chunks keep their id and vector across file edits (E2E-08), so stored citations stay valid; `document_uid` keeps ids unique across users and documents. *Superseded:* `{doc_id}-{ordinal:05d}-{hash8}` (ids changed on every edit). |
| Vector DB | **ChromaDB**, persistent, cosine, one collection per model + chunker major | Embedding model change never mixes vector spaces; scoping done by mandatory user/course metadata. |
| Parent store | SQLite now, PostgreSQL later | Parents are plain records needing lookups by key, not vectors. |
| OCR rules | Tesseract English; image confidence < 0.3 dropped, < 0.6 flagged; repeated logo OCR blanked; EMF/WMF mild skip | Noise must not be indexed; low-confidence text stays visible but flagged for the answer layer. |
| Title-only slides | Not indexed | They add no retrievable content. |
| Hidden slides | Kept by ingestion, excluded by chunking | Consumers choose; students do not expect hidden content in answers. |
| Citation strategy | `citation_label` on every chunk (`p. 14 > 8. Methodology`, `slide 7 > ...`, heading path for DOCX), computed from block page + heading path; prompts use `[S#]`, readers see `[n]` | Answers must point to a verifiable location. |
| Re-ingestion | `embedding_hash` (vector reuse) + `record_hash` (metadata refresh) + stale deletion, tombstone 7 days | Cheap, idempotent updates; prevents dangling `parent_chunk_id` after edits. |
| Grounding policy | **A** (remove uncited / unsupported sentences) until the judge is validated | The safest option; its cost with a non-citing 3B model is measured (11). With DeepSeek (11.2) A, B1 and C give identical correctness (68/72) and differ only in how much of each answer survives (72 / 13 / 24 sentences removed). B1/C remain offline experiments. *Decision (open)*: final policy, after judge validation. |
| Tests | unittest (not pytest) | pytest was not installed; suites also run under pytest. |
| Normalisation | Selective NFKC | Plain NFKC corrupts `x^2`, `H2O`, fractions. |

Historical decisions retained: additive schema (old fields kept), warnings never raise, readers are dependency-injected with a fake-OCR option for tests, per-document state kept local.

### Storage and Retention Policy

IntelliStudy uses persistent document storage. Uploaded documents are not deleted when a user logs out.

Policy:
- Each user receives a storage quota of 1 GB.
- Documents, chunks, embeddings and retrieval metadata remain associated with the user's account.
- Previously uploaded materials can be reused without re-running OCR, chunking or embedding generation.
- When a user reaches the 1 GB limit, further uploads are rejected until existing files are deleted.
- Deleting a document also removes its related chunks, embeddings and parent-chunk records.
- User and course scoping remains mandatory for all retrieval operations.

Implementation status (as of 2026-10-18, unchanged on 2026-11-15): this is an approved **policy**; most of it is not enforced yet.
- Already in place: mandatory `user_id` + `course_id` scoping on retrieval; chunk and embedding reuse for an unchanged file (`doc_id` is a content hash, re-ingestion is a no-op); vectors and parent chunks are persistent (Chroma + SQLite) and keyed per `document_uid`, so a document's records can be found and removed together.
- Still to build: per-user quota accounting and the upload rejection at 1 GB (needs the backend/PostgreSQL user model; see Known Issues, "Upload limits missing"); the API-level delete-document operation (the store side exists: `IndexingService.remove_document` removes a document's vectors and parents; the uploaded file and database rows are not covered); a lookup that lets a repeated upload find the existing `document_uid` before running OCR. The earlier 7-day tombstone decision applies to chunks made stale by re-ingestion, not to user-initiated deletes, which should remove records immediately.
- *Decision (open)*: the Figma design shows "Up to 100 MB per file" and "within 30 days" (deletion), and the architecture document FR-UPL-01 says 50 MB / 300 pages; all are unconfirmed placeholders.

---

## 6. Validation Summary

### Quality gates (*measured* 2026-11-15, 16:20-16:24 +02:00, after the 2026-11-15 changes)

| Gate | Command | Result |
|---|---|---|
| Unit/integration suite | `python -m unittest discover -s tests -t .` | Re-run 2026-11-15 after the evaluation fail-fast guard: **791 tests, OK** (6 skipped, 2 expected failures). Coverage run below: 783 tests run: **OK**, 0 failures, 0 errors, 6 skipped (opt-in real-model/tooling tests), 2 expected failures (211 s, under coverage) |
| Routing tests | `python -m unittest test_pptx_pipeline` | 10 tests, OK |
| Manual scripts (not gates) | `python test_pipeline.py`, `python test_docs_pipeline.py` | ingest correctly; `test_pipeline.py` needs `PYTHONIOENCODING=utf-8` when output is piped (an emoji in the PDF text); `test_docs_pipeline.py`'s default path `data/uploads/test1word.docx` no longer exists (pass `data/uploads/docs/test1word.docx`) |
| Ruff | `python -m ruff check ai tests` and `python -m ruff check evaluation` | all checks passed (both) |
| MyPy, `ai/` | `python -m mypy ai` | no issues in 57 source files |
| MyPy, `evaluation/` | `python -m mypy evaluation` | 17 errors in 5 older files (`figure_benchmark/synthetic.py`, `figure_benchmark/detection_eval.py`, `index_builder.py`, `retrieval_eval.py`, `answer_eval.py`); none in the files changed on 2026-11-15; pre-existing, not fixed (unrelated to this pass) |
| Coverage | `python -m coverage run --branch -m unittest discover -s tests -t . && python -m coverage report` | **94%** combined (`coverage report` TOTAL); lines 5,326 / 5,616 = **94.8%**, branches 1,604 / 1,772 = **90.5%**; scope `ai/` as configured in `pyproject.toml` (`evaluation/` is not measured) |

Re-run 2026-11-23 on Linux (`.venv`, Python 3.12.16): `INTELLISTUDY_SKIP_SLOW=1 python -m unittest discover -s tests -t .` -> **791 tests, OK** (17 skipped, 1 expected failure, 35 s); the higher skip count comes from the slow-test switch (not broken down per test). Ruff, MyPy and coverage were not re-run on Linux.
Baseline on 2026-11-15 before any change: 764 tests, OK (skipped 6, expected failures 2). Expected failures: Arabic reversed order (PyMuPDF limitation) and open finding E2E-09. Skipped: opt-in real-model/tooling tests.
Slow tests: `INTELLISTUDY_SKIP_SLOW=1`; real-model tests: `INTELLISTUDY_MODEL_TESTS=1`. `ruff format` has not been applied.
Performance (budgets asserted in the suite, *measured* 2026-11-15 baseline run): 3000 chunks indexed in 0.64 s (memory store) / 3.99 s (Chroma), 150-page PDF ingested in 2.2 s, 150-slide PPTX 1.2 s, 3000-paragraph DOCX 2.7 s, retrieval over 5000 vectors mean 45 ms / p95 51 ms.

### Defects found and fixed during validation
Hard-limit violations (oversize list item, wide table row, chart, long heading prefix), **concurrent PDF ingestion corrupting text/tables** (lock added), NaN/inf/zero vectors accepted, filter-operator injection, invisible-only text becoming chunks, stale `parent_chunk_id` after re-ingestion, parent-id collision across users, unbreakable tokens, invalid Chroma collection names, lone surrogates crashing hashing, query-dimension not validated, repeated embeddings, DOCX/PPTX text bypassing normalisation. Incident: a patch script truncated `cleaners.py` to zero bytes; restored in full and re-verified (patch scripts now encode before opening a file for write).

### Real-document validation (2026-10-17/18, all of `data/uploads/` at the time, full stack: BGE + persistent Chroma + SQLite)

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

(Since then `test1word.docx`, `test2word.docx` and `testword3.docx` were removed from the root of `data/uploads/` (deletion uncommitted); `test1word.docx` is in `data/uploads/docs/`. Counts above are pre-figure, pre-1.3.0 chunker.)

Zero validator problems and zero oversize chunks on every file. No hidden slides or charts exist in the real material, so those features are verified only by synthetic tests.

Findings: ~24 real queries checked by hand; top hits were correct for most (e.g. "What is separation of concerns?" -> p. 16 at 0.85; "What is a join point?" -> p. 17 at 0.85; "Who are the team members?" -> table at 0.64; "What is IntelliStudy?" -> OCR image chunk at 0.80), with correct citations, heading paths and OCR confidence propagation. Two real ingestion defects were found and fixed: (1) run-in bullet paragraph read as headings in `test2.pdf`; (2) PPTX slide-number placeholders ingested as content (12 junk chunks). Weaknesses are listed in section 7.

### 30-file end-to-end validation (2026-10-18)
The full dataset in `data/uploads/{docs,PDFs,pptx}` (10 DOCX, 10 PDF, 10 PPTX; 36,128 blocks, 14,542 chunks) was run through ingestion -> chunking -> BGE -> Chroma -> retrieval -> re-ingestion. Full report: [`e2e_validation_report.md`](e2e_validation_report.md). Six defects were found and fixed with failing-first tests in `tests/test_e2e_findings.py`: merged chunks lost section titles (chunker now 1.1.0), pipe characters in table cells rewritten, Symbol-font private-use glyphs, empty PPTX tables, rotated margin stamps (arXiv) becoming the root heading of PDFs, and PDF section titles not promoted to headings from the bookmark outline. Since fixed: slides whose titles are plain text boxes (E2E-07), retrieval threshold / reference-list ranking (E2E-10), chunk ids changing on every file edit (E2E-08). Still open: coarse citation of merged DOCX chunks (E2E-09), chunking time on a 27k-block DOCX (E2E-11), equation fragments as paragraphs (E2E-12). Same-file re-ingestion reproduced identical chunk ids for 30/30 files; scope filters leaked 0 of 5 combinations.

### Phase 0 pass (2026-10-19): E2E-07, E2E-10, figure infrastructure
E2E-07 and E2E-10 are closed (E2E-10 with measured evidence and a calibrated, model-bound policy); Phase 0 figure infrastructure is built and benchmarked. Highlights (full tables and caveats in [`phase0_report.md`](phase0_report.md)): retrieval hit@5 0.925 -> 0.962 and MRR 0.884 -> 0.917 with demotion + reranking on 53 answerable queries; shipped policy refuses 24/24 unrelated queries and no answerable one (in-sample); figure selection on 236 hand-labelled real candidates reaches precision 0.76 / recall 0.83 in-sample (about 0.68 / 0.82 leave-one-file-out for uncaptioned pictures); synthetic corpus: 12/12 figures found with exact captions and linked citing sentences, hit@1 for figure questions 0.278 -> 0.639. The 30 real files still chunk with 0 validator problems.

### Real-model evaluation (2026-10-25, re-scored 2026-11-15; DeepSeek 2026-11-23)
See section 11. Benchmark corpus (verified 2026-11-23 from the retrieval cache): 30 files (15 PDF, 10 PPTX, 5 DOCX) selected from the
36 in `data/uploads/` by `evaluation/index_builder.corpus_files` (5 excluded by name, 1 byte-identical duplicate of Section 03 dropped);
the 666 cached hits come from 28 of them, each matching the current file by full sha256 (hard_PDF_6 and hard_PDF_8 are never retrieved).

### Corpus coverage assessment (2026-11-15)
Full method, per-file verdicts and estimates: [`multimodal_ingestion_design.md`](multimodal_ingestion_design.md) section 14. Scope: the 30-file evaluation corpus.
- *Measured* composition (share of 172,662 indexed tokens): arXiv math papers 59% (10 files), DOCX samples 16% (5), lecture material 12% (6: AOP 1-2, Sections 01-03, SPE_l1), proposal + test PDFs 6% (3), slide templates 6% (6). No SmartArt and no native PowerPoint charts exist in the corpus.
- *Measured* channels reaching retrieval: native text 92.1% (about 3.5 points of it fragmented formula text), tables 4.9%, figure chunks 2.7%, image OCR 0.1%, whole-page OCR under 1%. Of 74 kept figures, 47 carry OCR text, 21 vector inner text, 4 a caption, 3 citing sentences, and 4 no text (not indexed).
- *Measured* largest category that reaches the index not at all: **104 Equation Editor (OLE `Equation.3`) objects in `SPE_l1.pptx`**.
- *Measured* Phase 0 insufficient: `Section 02 - Classical Encryption Techniques I.pptx`, `SPE_l1.pptx`; partial: `hard_PDF_1.pdf`, `Statistical Methods in Public Health ... Slidesgo.pptx`; the other 26 files sufficient or unaffected. Only 2 of 72 answerable QA cases are figure questions.
- *Estimate* (judgement, not measured): about 90-94% of the corpus's information is reachable as usable text (lecture material alone about 75-85%); roughly a third to a half of the remainder needs a vision model, the rest is formula / equation extraction. Expected Vision gain on the current QA benchmark: 0 to +2 cases, within noise.
- **Conclusion: Vision is not currently the highest-priority content gap.** Order: stronger-model evaluation -> equation extraction -> figure-question benchmark -> Vision bake-off (section 8).

---

## 7. Known Issues

Retrieval quality
- **Table retrieval is weak**: "What is the academic year?" ranked the OCR paragraph (0.62) above the table holding the answer (0.60). Tables are embedded as `Column: value`; raw questions match worse than expected.
- **Near-miss questions are only partly refused by retrieval** (on-topic, fact absent: 6 of 10 refused with the reranker policy, 40% cross-validated). The answer layer must still verify that the retrieved text supports the answer. End to end with Qwen2.5-3B, 10 of 10 near-miss cases were refused (10 of 11 before the a30 correction) near-miss cases were refused (*measured*, re-scored 2026-11-15). The relevance policy is calibrated on 87 queries and bound to BGE-small + MiniLM; recalibrate when either model, the chunker or the corpus type changes.
- Dense-math PDF chunks retrieve weakly (formulas embed poorly with BGE-small).
- Reranking costs about 2.5 s per query on CPU.
- **Table-of-contents pages are indexed** and can outrank real content for headings that appear in them (found by the answer-layer run); they should be down-ranked or excluded.

Ingestion
- **Table extraction**: merged cells in PDF tables leave empty spacer columns and a misaligned header (test2.pdf); several people in one cell are not split.
- `ocr_pages` statistic counts pages where OCR was attempted, not where it produced text (PPTX reported 11 with 1 useful image) - misleading.
- Scanned pages: no header/footer removal; heading detection is heuristic. Two-column PDFs and code panels are read top-to-bottom. SmartArt/OLE, DOCX headers/footers/footnotes/text boxes are not extracted. Equations are plain text.
- **Arabic extraction limitation**: PyMuPDF returns Arabic in visual (reversed) order (expected-failure test); OCR is English-only; BGE-small is English-only; no language detection or RTL handling.
- One PPTX slide (21) ends up with no content blocks after the placeholder fix; not inspected.
- **Figures (Phase 0 limits)**: selection is a baseline (about 1 in 3 kept uncaptioned pictures is not worth keeping, about 1 in 5 real figures is missed); captions on another page are not paired; unmatched extra panels of a multi-panel figure can be missed; SmartArt/grouped vector drawings are not detected as figures; DOCX figure selection has no hand-labelled real data; a figure with no caption/OCR/inner/alt text is recorded but not indexed. `statistics["image_ocr_count"]` counts images with OCR text, some now absorbed into figure blocks.
- Open evaluation findings: E2E-09 (coarse citation of merged DOCX chunks), E2E-11 (chunking time), E2E-12 (equation fragments).
- Open findings of the 2026-11-15 coverage assessment (not fixed; detail in `multimodal_ingestion_design.md` 14.5):
  - **F-COV-1** DOCX/PPTX chunks are tagged `source_kind = "ocr_page"` whenever any image on the page/slide was OCR'd, even when OCR produced nothing (all 8,089 native tokens of `sample-long.docx` are tagged as OCR); misleads OCR notices and source-based statistics.
  - **F-COV-2** Equation Editor (OLE `Equation.3`) objects are dropped and reach no block (only a WMF mild-skip warning). Largest category of content that does not reach the index. *Correction 2026-11-23 (measured):* `SPE_l1.pptx` holds **52 unique equations** on 21 slides; "104" counted each one twice (same `p:oleObj` in `mc:Choice` and `mc:Fallback`). All 52 carry MTEF v3 data in an `Equation Native` stream and are decodable without vision (8, item 16).
  - **F-COV-3** AOP1 p. 5 (Assessment Criteria): a timeline graphic flattens into one run-on paragraph and the CSE 447 / CSE 434 weights interleave. *Re-diagnosed 2026-11-23 (measured, `real_model_eval_report.md` section 13):* the flattening is **not** what loses a04 and x01. Every fact is in one intact chunk; dropping the timeline rows barely moves its scores (a04 rerank -9.5 -> -8.8 against a -3.3 cut-off; x01 gets worse). The chunk loses because it carries no document context: the queries name "the Aspect-Oriented course", the chunk only "Assessment Criteria". A document label (title or file name) lifts a04 to +2.3/+3.0 and x01 to +0.6/+2.1 (rank 1-2). Applied to the reranker only, it fixes x01 and x08 but blocks x18 (and x11) and lets 3 refuse-expected cases past the relevance policy, because the policy's thresholds were calibrated on unlabelled passages; a04 also needs the label in the embedded text (its chunk is outside the 20-candidate vector pool). Not implemented: it is a corpus-wide retrieval change (see 8, item 15c).
  - **F-COV-4** Section 03's one hand-labelled keeper is not selected; 2 Statistical Methods figures are kept without any text and are not indexed.
- Chroma on this machine: an index built by one process could not be re-opened by another (HNSW files missing) and cloud-sync folders lock segment files; the evaluation builds and queries in one process and indexes live outside the synced tree.

Answer layer and its evaluation
- **Answer quality with a real model** (*measured*, section 11): with Qwen2.5-3B refusal and attribution hold but correctness fails (0.56); the rule that removes uncited sentences removed 68 sentences in answerable cases, 39 of them entailed by the sources, and 6 answerable cases were refused because the model never cited. With DeepSeek flash (2026-11-23) correctness is 0.94 and no answered case is wrong; policy A still removed 72 sentences (mostly uncited list items and ":" introductions) without changing any case's correctness. *Decision (open)*: grounding policy (A keep / B1 repair-and-retag / C relax), after judge validation.
- **The NLI judge is too strict** (`cross-encoder/nli-deberta-v3-small`, 140-word windows, p >= 0.5): 24 of the 30 sentences it called unsupported in the Qwen run, and **74 of the 84 in the DeepSeek run** (`root_cause` judge check), share >= 80% of their content words with the sources. Faithfulness and hallucination numbers are pessimistic and not trustworthy in either direction until the judge is validated against hand labels (template ready, labels not done). This is now the blocker for a verdict on the critical criteria M3/M4.
- **Gold-set limits**: lexical gold facts (recall only; extra content is not penalised); one annotator who also built the system; `a33` and `a50` have fact-design issues left open (section 11).
- **Answer latency**: about 113 s per model-called case with Qwen2.5-3B on the old Windows CPU (239 s in the ablation run); 1.8 s mean per model call with hosted DeepSeek flash (2026-11-23). The architecture target is a full answer p95 < 12 s; end-to-end latency including retrieval and reranking (about 2.5 s on CPU) has not been measured with a hosted model.
- **Not built**: multi-turn history, streaming, HTTP endpoint, rate limits, cost accounting. Prompt injection is reduced (fencing, neutralised tags, citation validation), not eliminated; multilingual behaviour untested.
- *Fixed 2026-11-23 (branch `post-eval-quality`):* citation parsing split sentences at every newline, so list items under a cited introduction lost that citation and were removed by policy A (17 of 68 removals with Qwen; 17 list items and 16 ":" introductions of 72 with DeepSeek), and inline numbered lists were cut at each "1.". `ai/answering/citations.py` is now list-aware (items inherit their item's / introduction's tags, introductions inherit their items' tags, inherited tags still grounding-checked, no split after inline enumerators and common abbreviations, answers keep their line/list layout). Replay on the recorded DeepSeek replies: policy A removals 72 -> 34, correctness unchanged (`real_model_eval_report.md` section 12). Still open: fenced code blocks in answers are parsed line by line (12 of the remaining 34 removals are code lines of one answer, a11).
- **Evaluation instrument splits sentences differently from the parser** (`evaluation/answer_metrics.answer_sentences` splits after every period, so "1." list numbers and "e.g." fragments count as uncited claims). Official citation coverage therefore reads lower than the answers are: DeepSeek A after the parser fix 0.87 official vs 0.98 with a parser-aligned splitter. *Decision (open)*: align the instrument and re-score all runs (Qwen included) together, so numbers stay comparable.

Platform
- **Storage quota and delete cascade**: implemented in M2 (3.14): 1 GB per-user quota; deleting a document or course removes rows, vectors, parents and files.
- **Upload limits**: implemented in M2 (3.14): 100 MB per file, 300 pages/slides, ZIP-bomb and encryption checks, Pillow bomb guard, 30 s Tesseract timeout, sandboxed parser. Residuals F-M2-12..14 (contract Appendix D).
- **PostgreSQL persistence missing**: users, courses, documents and parent chunks live in SQLite/Chroma files only.
- **CI/CD partly in place**: GitHub Actions workflow (secret scan, dependency audit, lint, types, tests) green on every pushed backend milestone (latest: run #5, M3); no Dockerfile (docker-compose.yml is empty), Tesseract not in any image. Exact pins in `requirements.lock.txt`.
- Backend: auth, courses, upload, processing jobs and grounded chat are built (M0-M3, 3.12-3.15); summaries and quizzes are built and approved (M4, 3.16); quiz taking (M5) is not. Chroma is single-process (embedded).
- **Version control**: work up to 2026-11-15 is in `1660115` and `1a38fad`; post-evaluation work, the security contract and backend M0-M3 are on branch `post-eval-quality`, pushed to GitHub (latest `f05bf8e`, CI green), not yet merged to the default branch. `evaluation/results/` is git-ignored, so evaluation outputs (the Qwen runs, the retrieval cache, the DeepSeek runs) are local only; after the move to Linux they were missing until restored by hand from the old machine, which shows the risk. *Decision (open)*: whether to version them (or archive them elsewhere). *Superseded:* the OneDrive location of the Windows machine.

---

## 8. Roadmap

### Completed
1. PDF, PPTX, DOCX text extraction (OCR, tables, canonical schema, normalisation)
2. Chunking (hierarchical, parent-child, validated)
3. Embedding generation (BgeEmbedder)
4. ChromaDB integration (+ SQLite parent store)
5. Semantic retrieval (scoped, citations, parent expansion)
6. Re-ingestion system
7. Validation phase and real-document pass; 30-file end-to-end validation
8. E2E-07 (PPTX text-box titles) and E2E-10 (bibliography ranking, reranking, calibrated relevance policy)
9. Phase 0 figure infrastructure and benchmark
10. E2E-08: stable chunk ids across edits (chunker 1.3.0)
11. Answer Layer MVP: LLM adapter, context builder, prompt builder, citation injection, hallucination prevention, refusal logic, answer service
12. FigureDescriber plug-in interface (no vision model)
13. Real-model evaluation of the answer layer with Qwen2.5-3B (pre-registered plan, 111-case gold set, NLI-based metrics, partial grounding ablation, root-cause analysis) - 2026-10-25
14. Evaluation hardening for the next model (2026-11-15): raw-reply logging, retrieval-cache pinning, citation coverage, per-sentence attribution, per-answer hallucination rate, removed-sentence counter fix, offline policy replay (A / B1 experimental / C), hand-label template, a30 and x09 gold corrections, Qwen runs re-scored
15. Stronger-model run (2026-11-23): DeepSeek flash through the unchanged stack on the pinned retrieval cache, live policy A plus offline B1 / C replays, scored, root-caused and checksummed; evaluation milestone closed (section 11.2, `real_model_eval_report.md` section 11). Move to Linux with a pinned Python 3.12 environment the same day.

### In progress
- **Active priority (team decision recorded 2026-11-24): Backend Vertical Slice.** Security reference: [`backend_security_contract.md`](backend_security_contract.md) (authoritative for all backend work; rule ids cited in code and tests). Milestones: **M0 foundations + security baseline - done 2026-11-24 (3.12)**; **M1 identity, courses, ownership - done 2026-11-24 (3.13; gate: 79 items, CI green)**; **M2 documents + processing - done 2026-11-24 (3.14; gate [`SECURITY_MERGE_GATE.md`](SECURITY_MERGE_GATE.md) M2: 39 items, CI green)**; **M3 grounded chat - done and approved 2026-11-24 (3.15; release gate [`M3_RELEASE_GATE.md`](M3_RELEASE_GATE.md): 52 items, CI green; release blocker F-M2-10 closed)**; **M4 summaries + quiz generation - done and approved 2026-11-25 (3.16; release gate [`M4_RELEASE_GATE.md`](M4_RELEASE_GATE.md): 67 items, CI run #7 green; M4.1 quality patch). M5 next: release gate [`M5_RELEASE_GATE.md`](M5_RELEASE_GATE.md) drafted, awaiting team approval. Team decisions: summaries cached, deleted with their document; quizzes deleted with their only source document, invalidated (regenerate) when one of several sources is deleted; scope MCQ + true/false only, no short answer, essay, adaptive exams or LLM grading**; M2 documents + processing; M3 grounded chat; M4 summaries + quiz generation; M5 quiz taking, end-to-end demo, security verification. Quiz MVP (decided 2026-11-24): multiple choice + true/false, retry incorrect answers, auto-grading, citations; no short-answer, essay or adaptive exams. Equation extraction (item 16) and vision work (items 17-18) stay **parked**. The production-readiness items of section 12 (FW-1 to FW-5) are tracked there and do not block the backend, the frontend or the demo.
- Housekeeping: keep this file current; push branch `post-eval-quality`; archive `evaluation/results/` outside the machine (git-ignored, checksummed).
- Table retrieval quality and table spacer columns (known issues).

### Planned (next first)
15b. **Finish the stronger-model evaluation**: hand-label the judge-validation sheet (now the blocker for the M3/M4 verdict; consider adding DeepSeek sentences to it), decide the governing thresholds, then decide the grounding policy and calibrate `min_support`. (The newline/list citation-parsing property was fixed on 2026-11-23.)
15c. **Document context in chunks (F-COV-3; decision needed before implementing).** Add a document label (informative title, else file name) to the embedded text and the reranker passage, then re-embed the corpus, recalibrate the relevance policy on the 87 labelled queries and build a new pinned retrieval cache. *Expected gain (measured at chunk level, estimate overall):* at most +2 answerable cases (a04, x01): DeepSeek 68/72 -> about 70/72 (0.94 -> 0.97), within the benchmark's noise. *Costs/risks:* every chunk re-embedded; relevance policy re-calibrated; new retrieval baseline (the identical-retrieval comparison with the Qwen runs ends unless Qwen is re-run, about 3.5 h CPU); 11 of 28 retrieved files have a generic, missing or copied title and some file names are meaningless (`hard_PDF_1`), so the label needs a heuristic. Also relevant: table-of-contents pages outrank content for heading-like queries (p. 2 "Contents" is in a04's top 6).
16. **Equation extraction without vision** (investigation done 2026-11-23; F-COV-2 and E2E-12). **Parked** (2026-11-24); tracked as FW-1 in section 12.
    - *Measured:* `SPE_l1.pptx` holds 52 unique `Equation.3` objects on 21 slides (not 104); each is an OLE2 part with an `Equation Native` stream of MTEF v3 data (Equation Editor 3.0, Windows); no OMML (`m:oMath`) exists in the corpus. A throwaway decoder (not in the repository) parsed all 52 without error; characters, Greek letters, fractions, piles, sums and sub/superscripts are present in the data, but its template-selector table was guessed and must come from the official MTEF v3 specification (MathType SDK / Wiris "MTEF v.3 (Equation Editor 3.x)").
    - *Plan (not started):* (1) `ai/ingestion/equations.py`: a bounds-checked MTEF v3 reader producing linear text (e.g. `ρ = λ / (c·μ)`) and, optionally, LaTeX; Symbol-font code mapping for Greek/operators; never executes or trusts object data (Equation Editor 3.0 was an exploited attack surface, CVE-2017-11882), size and recursion limits, any decode failure = existing mild-skip warning. (2) PPTX reader: read `Equation.3` graphic frames once (ignore the `mc:Fallback` duplicate) and emit a new block type or a paragraph block marked as equation, in reading order, with the slide's heading path; confidence 1.0 when decoded. Needs `olefile` (new dependency) or a minimal CFB reader. (3) Chunking: equation text joins the surrounding prose (not an isolated atom), so `L = λW` lands beside its explanation; a chunker version bump changes only the affected chunk ids. (4) Tests: fixtures built from the 52 real objects with hand-checked expected text; synthetic malformed streams. (5) Measurement: the 111-case benchmark has no equation question (the SPE_l1 cases a31-a35, x03, x14 ask about prose), so add about 10-15 equation questions on SPE_l1 (Little's law, utilisation, M/M/1 and M/M/c state probabilities, M/M/1/K) and score retrieval before/after; DOCX equations (OMML or OLE) and the PDF fragment merge (E2E-12) follow as separate steps.
    - *Decisions (open):* text form (linear Unicode vs LaTeX vs both: embeddings read linear text better, LLMs read LaTeX well); whether to add `olefile`.
17. **Figure-question benchmark** on the content that needs it (Section 02, the SPE_l1 chart, hard_PDF_1, a few AOP diagrams; about 30-40 questions), Phase 0 baseline scored first. Annotation can start in parallel with 15. **Parked** (2026-11-24); tracked as FW-2 in section 12.
18. **Vision bake-off** (decision on a Vision LLM for figures): only on the benchmark of 17, requiring a measurable gain over Phase 0 (see `phase0_report.md` section 5); needs the team's answers on GPU, privacy and budget (`multimodal_ingestion_design.md` sections 12 and 14). **Parked** (2026-11-24); tracked as FW-2 in section 12.
19. Gemma 3 27B on the same protocol as 15, if an OpenAI-compatible endpoint (hosted or GPU) is available; Gemma 3 4B is not planned (another CPU floor).
20. Answer layer productisation: HTTP endpoint with the chat states of `figma_ui_context.md`, multi-turn history, rate limits and cost accounting, ToC-chunk handling.
21. Summarization
22. Citation-aware QA over the UI
23. Quiz generation
24. Adaptive learning engine, weak-topic detection, mastery estimation
25. Personalized exam generation, study recommendations
26. FastAPI backend (upload, jobs, auth) + PostgreSQL
27. React frontend
28. Docker/CI, upload limits, observability
29. Gemma 3 27B production migration; Arabic support

---

## 9. Answer Layer: MVP built, evaluated on two models, next steps

Goal: turn `RetrievalResult` into grounded, cited, refusable answers, independent of the LLM vendor. **All components below exist** (section 3.10, `answer_layer.md`); the table keeps the original plan for reference. What remains: real-model evaluations exist for Qwen2.5-3B (criteria not met) and DeepSeek flash (all judge-independent criteria met; section 11). Next: a trustworthy faithfulness measurement (judge validation), a grounding-policy decision, then an HTTP endpoint, multi-turn history, rate limits, cost accounting and ToC-chunk handling.

| Component | Responsibility |
|---|---|
| **LLM Adapter** | `LLMClient` protocol (`generate(messages, params) -> text, usage`); OpenAI implementation first, Gemma later; timeouts, retries, token accounting, deterministic low temperature. |
| **Context Builder** | Selects hits and parents under a token budget; de-duplicates overlapping parents; orders by relevance and document order; assigns stable source tags `[S1]..[Sn]` mapped to `citation_label`s; marks low-confidence OCR sources. |
| **Prompt Builder** | System prompt (answer only from sources, cite every claim, say when unknown), context block, question, output format; keeps templates versioned and testable. |
| **Citation Injection** | Parses `[S#]` tags in the answer, validates each against supplied sources, replaces with `citation_label` (file, page/slide, heading path), drops or flags unsupported tags. |
| **Refusal Logic** | Refuses when no hit passes the calibrated threshold, when sources do not cover the question, or the top sources are all low-confidence OCR; returns a structured refusal with the closest sources. |
| **Hallucination Prevention** | Retrieval threshold + re-rank, context-only prompting, citation validation, optional answer-support check (each sentence must map to a source), numeric/quoted-text verification, evaluation set of answerable/unanswerable questions. |
| **Answer Service** | Orchestrates retrieve -> build context -> prompt -> LLM -> validate citations -> `Answer(text, citations, refused, sources, usage)`; scope-checked per user/course; logging for evaluation. |

Prerequisites met: calibrated relevance policy, reranker, labelled evaluation set (E2E-10), stable chunk ids (E2E-08), a hardened evaluation harness (2026-11-15). Still open: improved table retrieval; the grounding check has been run on one real (3B) model, where it removed correct content whenever the model left sentences untagged; its policy is undecided.

**Stronger-model experiment: executed 2026-11-23 with DeepSeek** (protocol of [`real_model_eval_report.md`](real_model_eval_report.md) section 9, results in its section 10 and here in 11.2). The earlier *hypothesis* that a model which reliably emits `[S#]` tags loses far fewer answers to the citation rule is supported: 0 answers were refused as uncited (Qwen: 7). Still open: (1) judge validation; (2) which thresholds govern (eval plan vs architecture NFR-AIQ; false refusal 0.06 passes both); (3) the grounding-policy decision. No OpenAI or Gemini run exists (a Gemini AI Studio key created on 2026-11-23 returned 403 `PERMISSION_DENIED` / `API_KEY_INVALID` on `generateContent` at that time).

---

## 10. Production Readiness

**Ready**
- Ingestion of PDF/DOCX/PPTX into the canonical schema; chunking; embedding; vector indexing; scoped retrieval; re-ingestion; citations and OCR-confidence propagation. Backed by the suite in section 6, Ruff, MyPy (`ai/`), coverage and real-document passes.
- Concurrency of PDF ingestion (lock) and hostile-input handling (surrogates, invisible text, bad ids, NaN vectors, filter injection).

**Partially ready**
- **Retrieval quality**: good for prose and slides (hit@5 0.96 with reranking on the labelled set; the gold source reached the model in 69 of 71 answerable cases of the real-model run), weak for tables and dense math; a calibrated, model-bound relevance policy exists but only partly refuses near-miss questions.
- **Figures**: structure, captions, citations and a measured baseline selector exist; no generated descriptions, and selection accuracy is a baseline.
- **Table extraction** (merged cells), **scanned documents** (heuristic headings), **OCR statistics**.
- **Storage**: Chroma + SQLite work, but are single-process and not backed by PostgreSQL; tombstone retention is a policy, not yet a scheduled job.
- **Observability**: logging exists in modules; no metrics or tracing.

**Not ready**
- **Real-LLM answer quality verdict**: with DeepSeek flash every judge-independent criterion passes (correctness 0.94, refusal recall 1.00, false refusal 0.06, 0 fabricated numbers, 0 over-answers), but the critical faithfulness/hallucination criteria can only be decided once the NLI judge is validated; one run of one hosted model, no production model chosen. **Quizzes, adaptive learning** (not started).
- **Backend API, auth, multi-user data model, frontend** (skeleton or empty).
- **Upload limits and abuse protection**, **Docker/deployment**, **CI/CD**, **dependency pinning**.
- **Arabic / multilingual** content.
- **Version control hygiene**: work after commit `1660115` is uncommitted.

Verdict: the data, retrieval and answer-layer machinery (scoping, citations, refusal, grounding) are in place and tested. With a capable hosted model (DeepSeek flash, 2026-11-23) the unchanged stack answers 94% (68/72) of answerable questions correctly under the shipped policy, refuses every out-of-scope question and invents no numbers; with Qwen2.5-3B it was 56%. What is unproven is faithfulness, because the measurement (NLI judge) is not yet trustworthy. The remaining visible losses are chunks without document context (F-COV-3, 2 cases) and equations that never reach the index (F-COV-2). The system as a whole is not production-ready (no backend API, auth, frontend, deployment). Beyond those, section 12 lists the high-priority quality items (FW-1 to FW-5) to complete before production deployment.

---

## 11. Real-model evaluation of the Answer Layer

### 11.1 Qwen2.5-3B (2026-10-25; re-scored 2026-11-15)

Plan [`real_model_eval_plan.md`](real_model_eval_plan.md) (criteria fixed before any number; addendum §8 of 2026-11-15); results [`real_model_eval_report.md`](real_model_eval_report.md); code `evaluation/{answer_gold,answer_metrics,real_model_eval,policy_replay,root_cause}.py`; raw runs and the retrieval cache in `evaluation/results/runs_2026-10/` (sha256 in `SHA256SUMS.txt`; cache `c003e59f...`, verified identical to the retrieval both runs saw, 222/222 rows).

**What was run (*measured*).** One model, Qwen2.5-3B-Instruct (4-bit) through `OpenAICompatibleClient` against local Ollama, temperature 0, `num_ctx` 8192, identical cached retrieval for every case. Run A = the shipped stack (policy A). Run B = **partial ablation** (`GroundingPolicy(min_terms=10**6)`, policy C): sentences without a number skip every check (citation, support, quotes); sentences with numbers are still checked; the "at least one cited sentence" rule and the relevance policy stay on. Gemma was not run.

**Headline numbers.** Original (2026-10-25) and re-scored with the corrected gold and the new metrics (2026-11-15; same model outputs, no new generation):

| Metric (criterion) | Run A, 2026-10-25 | Run A, re-scored | Run B (partial ablation), 2026-10-25 | Run B, re-scored |
|---|---|---|---|---|
| Cases: answerable / near-miss | 71 / 11 | 72 / 10 | 71 / 11 | 72 / 10 |
| M1 correctness, all answerable (>= 0.70) | 39/71 = 0.55 | **40/72 = 0.56** (0.44-0.67) | 49/71 = 0.69 | **51/72 = 0.71** (0.60-0.80) |
| M1 correctness, answered (>= 0.80) | 39/59 = 0.66 | 40/60 = 0.67 | 49/60 = 0.82 | 51/61 = 0.84 |
| M2 gold source cited (>= 0.85) | 56/59 = 0.95 | 57/60 = 0.95 | 57/60 = 0.95 | 58/61 = 0.95 |
| M2 citation precision (>= 0.70) | 0.90 | 0.90 | 0.89 | 0.89 |
| Citation coverage (new; no criterion) | - | 77/79 = 0.97 | - | 77/119 = 0.65 |
| M3 faithfulness, NLI (>= 0.90) | 49/79 = 0.62 | 49/79 = 0.62 | 74/119 = 0.62 | 74/119 = 0.62 |
| M4 hallucination, answer level (<= 0.10) | 23/60 = 0.38 | 23/60 = 0.38 | 26/61 = 0.43 | 26/61 = 0.43 |
| Hallucination, sentence level pooled | 0.38 | 0.38 | 0.38 | 0.38 |
| Hallucination, sentence level mean per answer (new) | - | 0.33 | - | 0.33 |
| Fabricated numbers | 0/60 | 0/60 | 0/61 | 0/61 |
| M4 over-answering (<= 0.05) | 1/38 | **0/37** | 1/38 | **0/37** |
| M5 refusal recall (>= 0.95) | 37/38 = 0.97 | **37/37 = 1.00** | 37/38 = 0.97 | **37/37 = 1.00** |
| M5 false refusal (<= 0.20) | 12/71 = 0.17 | 12/72 = 0.17 | 11/71 = 0.15 | 11/72 = 0.15 |
| M6 completeness, answered (>= 0.70) | 0.61 | 0.61 | 0.76 | 0.78 |
| M7 cited sentences entailed by their sources (>= 0.85) | 40/77 = 0.52 | 40/77 = 0.52 | 40/77 = 0.52 | 40/77 = 0.52 |
| Substantive sentences attributed (new) | - | 40/79 = 0.51 | - | 40/119 = 0.34 |
| M7 gold facts found in a cited source (>= 0.85) | 81/82 = 0.99 | 83/84 = 0.99 | 100/101 = 0.99 | 103/104 = 0.99 |
| Sentences removed by grounding (reporting) | 60 (under-count) | 74 | 24 (under-count) | 26 |

95% Wilson intervals in brackets. Run B's re-scored correctness (0.71) crosses the 0.70 line **only because of the post-hoc gold corrections** (a30, x09), on a configuration that is not shippable (35% of its substantive sentences carry no citation), with an interval of 0.60-0.80. It is not evidence that the criterion is met. Run A, the shipped stack, stays at 0.56.

**Failure categories of run A** (2026-10-25 manual review of 33 failures; categories exclusive): retrieval 3 (a04, x01, x08); missing citations 15 (9 recoverable with the filter off, 6 never cited after the repair attempt); grounding filter (support/number) 0 as primary cause; prompt 1 (a39); model reasoning 10; judge/gold disagreement 4 (x09, a50, a33, a30). Corrections of 2026-11-15: a30 is answerable (below), so it is no longer a label problem; x09 counts correct in run B; a33 and a50 stay open. Retrieval delivered the gold source in 69/71 answerable cases.

**Post-evaluation label corrections (2026-11-15, post hoc).**
- `a30` "How does the Hill cipher use a key matrix?": near-miss -> **answerable**. Evidence: Section 02 slide 12 "Encryption is done by linear equation: m C.T Letters = mxm Key Matrix multiplied by m P.T Letters" (slide 15: decryption by the inverse; slide 16: k = C x P-1). The earlier near-miss label looked only at Section 03, which lists the cipher (slide 3) and has exercises (slide 20) without explaining it; the question is course-scoped. Qwen's answer cited slide 12.
- `x09`: added "spread around in the code" (the source's own definition of scattering).
- `a33`, `a50`: reviewed, unchanged - the misses are fact-design issues (which facts and how many are required), not wording variants. *Decision (open)*.

**Limits.** One model; one annotator; lexical gold (recall only); small single-corpus set (about +/-0.10 on proportions near 0.5; differences below about 0.15 are not meaningful between independent runs); NLI judge pessimistic by an unquantified amount; partial ablation; CPU latency (about 113 s per answer) says nothing about production speed; raw model replies were not stored in these runs, so they cannot be replayed under policy B1.

### 11.2 DeepSeek (2026-11-23)

Full record: [`real_model_eval_report.md`](real_model_eval_report.md) section 10. Outputs in `evaluation/results/runs_2026-11/`.

**What was run (*measured*).** The section-9 protocol unchanged: requested model `deepseek-chat` at `https://api.deepseek.com`; every reply reports `deepseek-flash` (the legacy name was announced for discontinuation on 2026-07-24 and is still served); non-thinking (completion tokens per answer word median 1.44, all `finish_reason` = `stop`). Live run under policy A; policies B1 and C replayed offline on the same recorded replies. Same retrieval cache (`c003e59f...`) as both Qwen runs, same 111 ids, 0 endpoint errors, 75 model calls, 1.8 s mean per call, about 111k prompt + 10k completion tokens. `root_cause_deepseek-chat.json` (A vs C) and `runs_2026-11/SHA256SUMS.txt` (14 artifacts, verified) written 2026-11-23. **Evaluation milestone closed 2026-11-23**; final summary in `real_model_eval_report.md` section 11.

**Headline (DeepSeek A vs Qwen A re-scored).** Correctness all answerable 68/72 = **0.94** (0.87-0.98) vs 0.56; of answered 68/68 vs 0.67; gold source cited 0.99 vs 0.95; citation precision 0.94 vs 0.90; refusal recall 37/37 both; false refusal **4/72 = 0.06** vs 0.17; over-answering 0/37 both; completeness (answered) 0.96 vs 0.61; fabricated numbers 0/68; gold facts in a cited source 153/154. NLI-judged: faithfulness 0.65 vs 0.62, answer-level hallucination 0.60 vs 0.38, sentence-level 0.35 vs 0.38, cited sentences entailed 0.54 vs 0.52. B1 and C replays: identical correctness (68/72), removals 13 (B1) and 24 (C) vs 72 (A).

**Verdict under the plan's rule.** All non-NLI criteria pass; the three NLI-judged criteria fail, two of them critical (M3, M4), so the formal verdict is "not acceptable" **pending judge validation**: `root_cause`'s judge check finds 74 of the 84 sentences the judge rejects to be judge disagreements (Qwen: 24 of 30), and the higher answer-level rate follows from longer answers (4.0 substantive sentences per answer vs 1.3), not from a higher per-sentence rate (0.35 vs 0.38).

**Failures (`root_cause`).** Retrieval 3: a04 and x01 (gold page AOP1 p. 5 never retrieved; the model then declined; root: the chunk carries no document context, see F-COV-3 in 7) and x08 (relevance policy refused with the gold in context). Model reasoning 1: a53 (dense-math question, declined with gold in context). None recoverable with grounding off. No answered case is wrong.

**Conclusions (*measured*, identical retrieval for every run).**
- *Retrieval is not the bottleneck:* the gold source reached the model in 70/72 answerable cases; retrieval-stage failures are the same 3 cases for both models and cap correctness at 69/72.
- *Model capability was the bottleneck:* on the 69 cases where retrieval delivered the gold source, correctness is 40/69 (Qwen A), 51/69 (Qwen C), 68/69 (DeepSeek A, B1, C). Paired A vs A: DeepSeek alone correct on 28 cases, Qwen alone on 0 (exact McNemar p = 7.5e-9). Qwen's 19 wrong-with-gold-in-context answers and 7 uncited refusals do not occur with DeepSeek.
- *Grounding policy is secondary and model-dependent:* switching it off recovered 11 Qwen cases and 0 DeepSeek cases.
- Caveat: "model" includes size, 4-bit quantisation and local vs hosted serving; one run per model.

**Limits.** One run of one hosted model (temperature 0 not bit-deterministic; variation not measured); same gold, judge and corpus limits as 11.1; the provider maps the model name to whatever it currently serves.

---

## 12. Future Work (High Priority Before Production Deployment)

These items are **not current sprint work** and do **not** block backend implementation, frontend implementation or demo
delivery. They are high-value production-readiness improvements that should be completed **before production deployment**
and stay explicitly tracked here. They do not change the order of section 8: the active priority is the Backend Vertical
Slice; equation extraction and vision work stay parked. Status lines restate measured facts from the sections referenced.

### FW-1: Advanced Equation Extraction
Current status:
- 52 unique Equation Editor objects identified in `SPE_l1.pptx` (21 slides; the earlier count of 104 counted each object twice).
- All equations are recoverable from their embedded `Equation Native` streams (MTEF v3; a throwaway decoder read 52/52).
- The current benchmark contains no equation-focused questions.

Goal:
- Extract equations into a canonical structured form.
- Store linear-text and LaTeX representations.
- Index equations for retrieval.
- Add equation-focused benchmark questions.

Detail: section 8 item 16 (plan, security limits, open decisions), section 7 F-COV-2; related E2E-12 (fragmented PDF formulas).

### FW-2: Figure and Diagram Understanding
Current status:
- Figure infrastructure exists (detection, selection, figure chunks and citations; section 3.8).
- Figure retrieval exists.
- Vision is not currently required for benchmark performance (2 of 72 answerable cases are figure questions; coverage assessment in section 6).

Goal:
- Build a dedicated figure benchmark.
- Support diagrams, workflow charts, architecture figures, scientific figures and research-paper visuals.
- Evaluate vision-capable models.
- Improve figure-grounded citation quality.

Detail: section 8 items 17-18, section 3.11 (`FigureDescriber` plug-in point), `multimodal_ingestion_design.md` sections 12 and 14.

### FW-3: Judge Validation and Evaluation Reliability
Current status:
- The NLI judge appears overly strict (judge disagreements: 24 of 30 rejected sentences for Qwen, 74 of 84 for DeepSeek).
- The human-labelled validation set is not yet completed (`evaluation/handlabel/`).

Goal:
- Validate faithfulness metrics against human labels.
- Recalibrate faithfulness and hallucination scoring.
- Increase the trustworthiness of evaluation results.

Detail: section 7 (NLI judge), section 8 item 15b, section 11.2 (verdict pending judge validation).

### FW-4: Advanced Citation and Attribution Quality
Current status:
- Citation parsing improvements completed (list-aware parser, 2026-11-23; policy A removals 72 -> 34 on the DeepSeek replies).
- Remaining edge cases include code blocks (fenced code parsed line by line) and metric alignment (the evaluation splitter differs from the parser).

Goal:
- Improve sentence attribution accuracy.
- Improve citation coverage reporting.
- Improve grounding robustness.
- Ensure citations remain highly reliable at production scale.

Detail: section 7 (citation-parsing and evaluation-splitter bullets), `real_model_eval_report.md` section 12; grounding-policy decision in section 8 item 15b.

### FW-5: Stress-Test Corpus Expansion
Current status:
- The evaluation corpus contains 30 benchmark documents (15 PDF, 10 PPTX, 5 DOCX; 111 cases).
- DeepSeek achieved strong results on the existing benchmark (correctness 68/72 = 0.94; section 11.2).

Goal:
- Create a harder benchmark corpus.
- Include equation-heavy PDFs.
- Include table-heavy PDFs.
- Include research papers.
- Include diagram-heavy educational content.
- Expand evaluation coverage beyond the current benchmark.

Detail: section 6 (corpus composition and coverage assessment), section 7 (table retrieval, dense-math retrieval).

---

## 13. Changelog of this file

- **2026-11-25 M4 approved**: CI run #7 green on `c1ee771` (M4 + M4.1); official regeneration after M4.1: 8 of 10 questions (19 generated; drops: 9 `second_correct_option`, 1 `evidence`, 1 `unsupported_answer`); gate section 3 signed; contract v1.9. M5 release gate drafted (`docs/M5_RELEASE_GATE.md`, v1.0, awaiting team approval; no M5 code).
- **2026-11-24 M4.1 patch**: F-M4-05 (sentence splitter abbreviations, summary fragments) and F-M4-06 (quiz evidence across line-end word splits) fixed; F-M4-07 recorded; manual DeepSeek run recorded in M4 gate v1.2 section 2.12; contract v1.8; §3.16 bullet.
- **2026-11-24 M4 implemented**: new §3.16 (summaries, quizzes, generation runner, deletion rules; 67 gate tests passing locally; findings F-M4-01..04); §8 milestone line; contract v1.7; M4 gate v1.1 (PRV-04 wording) with evidence section 2.11.
- **2026-11-24 F-M3-05 fixed** (before M4, team decision): usage ledger `llm_usage` is the single source of truth for the daily token budget; §3.15 note; contract v1.6.
- **2026-11-24 M4 release gate**: `docs/M4_RELEASE_GATE.md` (67 items in 10 areas: summary and quiz isolation, shared token budget, provider failures, summary citation validation, quiz answer validation, no answer-key leakage, deletion and invalidation, summary storage, injection and scope); contract v1.5 (ISO-03, ISO-04, UPL-16; finding F-M3-05: deleting a conversation refunds the M3 token budget); §8 milestone line.
- **2026-11-24 M3 approved**: CI run #5 green on `f05bf8e`; release blocker F-M2-10 closed (contract v1.4); M3 gate signed off; M2 CI (run #3) recorded; §7 platform bullets brought up to date (quota, upload limits, CI, backend endpoints); §8 marks M4 next.
- **2026-11-24 M3 implemented**: new §3.15 (conversations and messages, chat flow, states, provider failure handling; 52 gate tests passing locally; findings F-M3-01..04); §8 milestone line; contract v1.3; evidence section 2.9 in `M3_RELEASE_GATE.md`.
- **2026-11-24 M3 release gate and release blocker F-M2-10**: `docs/M3_RELEASE_GATE.md` (52 items in 8 areas: READY-only retrieval, cross-user retrieval isolation, citation presence, citation ownership, prompt injection, chat states, DeepSeek failure handling, retrieval scope); scoped retrieval layer `backend/app/services/retrieval.py` with tests G3-RDY-01..07; contract v1.2.
- **2026-11-24 M2 implemented**: new §3.14 (upload, storage, sandboxed parsing, jobs; 39 gate tests; findings F-M2-01..14); §3.13 records the green M1 CI run; §8 milestone line; contract v1.1 (UPL-06, UPL-08, UPL-12, Appendix D); M2 section in `SECURITY_MERGE_GATE.md`.
- **2026-11-24 M1 implemented**: new §3.13 (endpoints, password, token, refresh, lockout and ownership design; 80 gate tests); §3.12 records the green M0 CI run; §8 milestone line. Gate evidence table added to `SECURITY_MERGE_GATE.md`; `backend/README.md` endpoint table.
- **2026-11-24 M1 security merge gate**: `docs/SECURITY_MERGE_GATE.md` added and linked from §8; M0 CI confirmed green on GitHub (run 1, commit `7892321`: secret scan, dependency audit, lint, types, tests).
- **2026-11-24 M0 backend foundation**: new §3.12; §4 backend tree and environment versions (Pillow 13, SQLAlchemy, Alembic); §7 platform bullets (CI partly in place, backend foundation, version control); §8 milestone list and the approved quiz-MVP scope; tech-stack line updated. Contract: Appendix C (recorded dependency exceptions) and decided items (CORS, JWT, quiz scope).
- **2026-11-24 backend security contract**: `docs/backend_security_contract.md` added (ownership, isolation, retrieval, vector-store and file-storage guarantees, JWT and refresh-token model, secrets, upload rules, security test matrix); §8 "In progress" and the related-documents list link it.
- **2026-11-24 priorities and future-work register** (docs only): Backend Vertical Slice recorded as the active priority in §8 "In progress"; items 16-18 marked parked (FW-1, FW-2) without reordering §8; new §12 "Future Work (High Priority Before Production Deployment)" with FW-1 to FW-5; §10 points to it; changelog renumbered 12 -> 13; header updated.

- **2026-11-23 post-evaluation quality pass** (branch `post-eval-quality`): §7 citation-parsing bullet marked fixed (list-aware parser, replay-measured), new bullet on the evaluation splitter; F-COV-3 re-diagnosed (document context, not timeline flattening); §8 items 15b and 15c; §10/§11.2 wording. `real_model_eval_report.md` sections 12 (parser fix) and 13 (F-COV-3).
- **2026-11-23 evaluation milestone closed**: `root_cause_deepseek-chat.json` and `runs_2026-11/SHA256SUMS.txt` produced; §11.2 failures re-stated from `root_cause`, judge check stated with the `root_cause` instrument (74/84), conclusions added (retrieval not the bottleneck, model capability was); §7 NLI bullet, §8 items 15 and housekeeping updated. `real_model_eval_report.md` section 11 (final summary) added.
- **2026-11-23 DeepSeek evaluation, Linux environment, equation-extraction investigation** (no product code change): header commit state (`1a38fad`); §1 LLM strategy; §3.10 status and DeepSeek line; §4 folder tree (no `frontend/`, no empty backend packages, `runs_2026-11/`, `requirements.lock.txt`) and Linux / Python 3.12 `.venv` environment; §5 grounding-policy row; §6 Linux test re-run (791 OK) and verified benchmark corpus (30 files: 15 PDF, 10 PPTX, 5 DOCX); §7 answer-quality, NLI-judge, latency, citation-parsing, CI and version-control bullets, F-COV-2 corrected to 52 unique equations; §8 item 15 completed, 15b and item 16 (equation-extraction findings and plan) added; §9 experiment executed; §10 verdict; §11.2 DeepSeek results. `real_model_eval_report.md` section 10 added; F-COV-2 correction also in `multimodal_ingestion_design.md` 14.5.

- **2026-11-15 corpus coverage assessment** (docs only, no code change): §6 new subsection with measured composition, reach by channel, Phase 0 per-file verdicts and labelled estimates; §3.8 real-corpus reach note; §7 open findings F-COV-1 to F-COV-4; §8 planned order changed to stronger-model evaluation -> equation extraction -> figure-question benchmark -> Vision bake-off (Gemma and later items renumbered 19-29). Full assessment in `multimodal_ingestion_design.md` section 14.
- **2026-11-15 consolidation pass** (no behaviour change to the product): header date and accurate commit state; full related-documents list; schema references 2.0 -> 2.1 (§2, §3.1); §3 subsections reordered 3.1-3.11; §3.9/§4 evaluation harness and folder tree match the repository; §3.10 status records the Qwen2.5-3B evaluation and policy A as the production default; §5 chunk-ID decision updated to chunker 1.3.0 (`c-{hash12}` / `p-{hash12}`), grounding-policy row added; §6 quality gates re-run and recorded with commands; §7 answer-layer issues rewritten from real-model evidence (judge limits, latency, list-citation property, gold limits) and version-control bullet corrected; §8 Qwen evaluation and evaluation hardening completed, stronger-model experiment next; §9/§10 updated to the measured state; appended evaluation section integrated as §11 with re-scored numbers and the a30/x09 corrections; status labels (measured / decision / hypothesis / superseded) introduced. Four design documents received superseded-status banners; `figma_ui_context.md.md` renamed to `figma_ui_context.md`.
- 2026-10-25: real-model evaluation appended (now §11).
- 2026-10-19: answer layer MVP, E2E-08, FigureDescriber plug-in point.
- 2026-10-18/19: validation phase, 30-file end-to-end validation, Phase 0.

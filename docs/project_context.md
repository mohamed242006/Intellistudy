# IntelliStudy - Project Context (single source of truth)

**IntelliStudy: AI-Powered Lecture Summarization and Adaptive Exam Generation System using Retrieval-Augmented Generation (RAG)**
Graduation project, Computer Engineering, Ain Shams University, team of four.

> **How to use this file.** It describes what exists in the repository today, why it was built that way,
> how it was validated, and what is still open. Read sections 2-5 before touching `ai/`.
> Assumed reader: an engineer or an AI assistant continuing the work with no other context.
> Last updated: 2026-11-15 (consolidation pass, see 12). Commit state: commit `1660115` holds ingestion, chunking,
> embedding, Chroma, the SQLite parent store and the base retrieval service; everything added since (answer layer,
> retrieval add-ons `references/rerank/assessment/calibration`, figure modules, `evaluation/`, most of `docs/`) is
> uncommitted as of this date (see 7 and 10).
>
> **Labels used for status.** *Measured* = a number produced by a command on this repository (the date says when).
> *Decision (open)* = a choice nobody has made yet. *Hypothesis* = an expectation not yet measured. *Superseded* =
> historical information kept for context; the current value is stated next to it.

Related documents in `docs/`: `chunking_design_spec.md` (original chunking rules; ids, kinds and thresholds superseded by 3.2),
`chunking_architecture.md` (chunking code as first built), `embedding_retrieval_architecture.md`, `validation_progress.md`
(validation log, closed 2026-10-18), `e2e_validation_report.md` (30-file run), `multimodal_ingestion_design.md` (figure design),
`phase0_report.md` (E2E-07, E2E-10, figure Phase 0), `answer_layer.md` (answer layer MVP, E2E-08), `real_model_eval_plan.md` /
`real_model_eval_report.md` (Qwen2.5-3B evaluation), `figma_ui_context.md` (UI source of truth), `IntelliStudy_Architecture_Design_v1.1.docx`
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
Frontend React + Tailwind (not started; `figma_ui_context.md` recommends React + TypeScript) · Backend Python/FastAPI (skeleton only) · AI: sentence-transformers, ChromaDB, RAG ·
DB: PostgreSQL planned (SQLite used now for parent chunks) · Documents: PyMuPDF, python-docx, python-pptx, pdfplumber, Pillow,
Tesseract/pytesseract · Optional speech: Whisper · Deployment: Docker/Compose (not started) · VCS/CI: Git/GitHub Actions (CI not started).

### LLM strategy
Phase 1 OpenAI API; Phase 2 self-hosted Gemma 3 27B. The architecture stays model-agnostic (an adapter interface) so the swap is small.
The only real model evaluated so far is Qwen2.5-3B through local Ollama (section 11), a floor for the stack, not the planned model.

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

### 3.10 Answer Layer MVP (`ai/answering/`) - DONE; evaluated on one real model (Qwen2.5-3B); acceptance criteria not met (see 11)
Details, guarantees and results: [`answer_layer.md`](answer_layer.md) (MVP record) and section 11 (real-model evaluation).
- `llm.py` LLM adapter (`LLMClient` protocol; `OpenAICompatibleClient` over stdlib HTTP for OpenAI / vLLM / Ollama / self-hosted Gemma or Qwen; `ExtractiveLLM` no-model baseline; `ScriptedLLM` for tests); `context.py` Context Builder (numbered sources S1..Sn, budget, de-duplication, wider-section context, generated/low-confidence flags); `prompt.py` Prompt Builder (versioned `answer-1`, fenced sources, neutralised tags); `citations.py` Citation Injection (validated `[S#]` -> reader-facing `[n]`); `grounding.py` Hallucination Prevention (per-sentence citation, word, number and quotation support; failing sentences removed); `refusal.py` Refusal Logic (pre-model and post-model, reasons `no_results`, `not_relevant`, `model_declined`, `uncited_answer`, `unsupported_claims`, `llm_unavailable`); `service.py` Answer Service.
- Guarantees: retrieval scoped to one user and course; no uncited or ungrounded answer is returned; unrelated questions are refused before the model is called; a model outage is a refusal; source text cannot close its fence or impersonate a citation; answers resting on AI-generated figure text are flagged.
- Production grounding policy: **A** (the shipped default above: uncited or unsupported sentences are removed). It stays the default until the stronger-model comparison is done (section 9). Alternative policies B1 and C exist only in the offline evaluation harness (3.9).
- Measured with the extractive baseline on 87 labelled queries (2026-10-19): 24/24 unrelated refused before any model call; near-miss 9/10 refused; answerable 45/53 answered, 37/53 citing the expected source. This evaluates the machinery, not a language model's writing.
- Measured with a real model (2026-10-25, Qwen2.5-3B, 111 cases): refusal and attribution hold; correctness fails its criterion. Summary in section 11.

### 3.11 FigureDescriber plug-in point (`ai/ingestion/figure_description.py`) - DONE (no vision model included)
`FigureDescriber` / `FigureCropper` protocols, `PdfFigureCropper`, `enrich_figures` (never overwrites source text; rejects descriptions whose numbers are not in the author's text; caches by image hash + model + prompt version; one failing figure never stops the rest), `NullFigureDescriber`, `StubFigureDescriber`. The chunker renders a described figure with a labelled generated-description line, and because ids depend on text only, enrichment renames only the figure chunks. A real describer (Qwen2.5-VL or other) is adopted only if it clearly beats the Phase 0 baseline on the figure benchmark and on real figure-heavy documents. PPTX/DOCX croppers do not exist yet.

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
├── backend/
│   ├── app/           main.py (FastAPI skeleton, GET / only) + empty api/ core/ models/ services/ packages
│   └── requirements.txt   fastapi, uvicorn, pymupdf, python-docx, python-pptx, pdfplumber, pillow, pytesseract, chromadb, sentence-transformers (unpinned)
├── frontend/          empty
├── evaluation/        retrieval_dataset, index_builder, retrieval_eval, answer_eval, answer_gold, answer_metrics,
│                      real_model_eval, policy_replay, root_cause, handlabel/ (judge-validation template),
│                      figure_benchmark/ (labels, synthetic corpus, evaluators),
│                      results/ (git-ignored outputs; runs_2026-10/ = Qwen runs + retrieval cache)
├── tests/             38 files: 33 test modules + 5 support files (chunk_fixtures, pdf_fixtures, pptx_fixtures,
│                      random_docs, __init__)
├── data/uploads/      root: 2 Aspect-Oriented lecture PDFs, Intellistudy_final_proposal.pdf, Section 03 PPTX, test.pdf, test2.pdf;
│                      docs/ (10 DOCX), PDFs/ (10 PDF), pptx/ (10 PPTX)
├── docs/              this file; chunking_design_spec, chunking_architecture, embedding_retrieval_architecture (historical, bannered);
│                      validation_progress, e2e_validation_report, multimodal_ingestion_design, phase0_report, answer_layer (bannered),
│                      real_model_eval_plan, real_model_eval_report, figma_ui_context, IntelliStudy_Architecture_Design_v1.1.docx
├── pyproject.toml     ruff / mypy / coverage configuration
├── docker-compose.yml EMPTY (no Dockerfile)
├── test_pptx_pipeline.py (10 routing tests), test_docs_pipeline.py, test_pipeline.py (manual dump scripts)
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
| Chunk IDs | **Stable, content-based** (chunker 1.3.0): `c-{hash12 of the chunk text}` (`.{n}` for repeated identical text), parents `p-{hash12}`; vector id `{document_uid}:{chunk_id}` | Unchanged chunks keep their id and vector across file edits (E2E-08), so stored citations stay valid; `document_uid` keeps ids unique across users and documents. *Superseded:* `{doc_id}-{ordinal:05d}-{hash8}` (ids changed on every edit). |
| Vector DB | **ChromaDB**, persistent, cosine, one collection per model + chunker major | Embedding model change never mixes vector spaces; scoping done by mandatory user/course metadata. |
| Parent store | SQLite now, PostgreSQL later | Parents are plain records needing lookups by key, not vectors. |
| OCR rules | Tesseract English; image confidence < 0.3 dropped, < 0.6 flagged; repeated logo OCR blanked; EMF/WMF mild skip | Noise must not be indexed; low-confidence text stays visible but flagged for the answer layer. |
| Title-only slides | Not indexed | They add no retrievable content. |
| Hidden slides | Kept by ingestion, excluded by chunking | Consumers choose; students do not expect hidden content in answers. |
| Citation strategy | `citation_label` on every chunk (`p. 14 > 8. Methodology`, `slide 7 > ...`, heading path for DOCX), computed from block page + heading path; prompts use `[S#]`, readers see `[n]` | Answers must point to a verifiable location. |
| Re-ingestion | `embedding_hash` (vector reuse) + `record_hash` (metadata refresh) + stale deletion, tombstone 7 days | Cheap, idempotent updates; prevents dangling `parent_chunk_id` after edits. |
| Grounding policy | **A** (remove uncited / unsupported sentences) until the stronger-model comparison | The safest option; its cost with a non-citing 3B model is measured (11); B1/C remain offline experiments. *Decision (open)*: final policy. |
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

Baseline on the same day before any change: 764 tests, OK (skipped 6, expected failures 2). Expected failures: Arabic reversed order (PyMuPDF limitation) and open finding E2E-09. Skipped: opt-in real-model/tooling tests.
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

### Real-model evaluation (2026-10-25, re-scored 2026-11-15)
See section 11.

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
  - **F-COV-2** Equation Editor (OLE `Equation.3`) objects are dropped: 104 in `SPE_l1.pptx` reach no block (only a WMF mild-skip warning). Largest category of content that does not reach the index.
  - **F-COV-3** AOP1 p. 5 (Assessment Criteria): a timeline graphic flattens into one run-on paragraph and the CSE 447 / CSE 434 weights interleave; likely root of answer failures a04, x01, x18.
  - **F-COV-4** Section 03's one hand-labelled keeper is not selected; 2 Statistical Methods figures are kept without any text and are not indexed.
- Chroma on this machine: an index built by one process could not be re-opened by another (HNSW files missing) and cloud-sync folders lock segment files; the evaluation builds and queries in one process and indexes live outside the synced tree.

Answer layer and its evaluation
- **Answer quality with a real model** (*measured*, Qwen2.5-3B, 111 cases; section 11): refusal and attribution hold, correctness fails its criterion. The rule that removes uncited sentences removed 68 sentences in answerable cases, 39 of them entailed by the sources; 6 answerable cases were refused because the model never cited. *Decision (open)*: grounding policy (A keep / B1 repair-and-retag / C relax).
- **The NLI judge is too strict** (`cross-encoder/nli-deberta-v3-small`, 140-word windows, p >= 0.5): 24 of the 30 sentences it called unsupported in the original run share >= 80% of their content words with the sources. Faithfulness and hallucination numbers are therefore pessimistic and not trustworthy in either direction until the judge is validated against hand labels (template ready, labels not done).
- **Gold-set limits**: lexical gold facts (recall only; extra content is not penalised); one annotator who also built the system; `a33` and `a50` have fact-design issues left open (section 11).
- **Answer latency**: about 113 s per model-called case with Qwen2.5-3B on this CPU (239 s in the ablation run); the architecture target is a full answer p95 < 12 s. Says nothing about a hosted or GPU model.
- **Not built**: multi-turn history, streaming, HTTP endpoint, rate limits, cost accounting. Prompt injection is reduced (fencing, neutralised tags, citation validation), not eliminated; multilingual behaviour untested.
- Citation parsing splits sentences at every newline, so list items under a cited introduction lose that citation and are removed by policy A (17 of the 68 removed sentences start with a list marker). This is a stack property, independent of the model.

Platform
- **Storage quota and delete cascade not implemented**: the 1 GB per-user quota and cascading document deletion are policy only (see Storage and Retention Policy).
- **Upload limits missing**: no file-size, page/slide-count, image-count, zip-bomb guard or Tesseract timeout.
- **PostgreSQL persistence missing**: users, courses, documents and parent chunks live in SQLite/Chroma files only.
- **CI/CD missing**: no GitHub Actions, no Dockerfile (docker-compose.yml is empty), requirements unpinned, Tesseract not in any image.
- Backend is a skeleton (`GET /` only): no upload API, auth or job queue. Chroma is single-process.
- **Version control**: commit `1660115` holds the stack up to base retrieval; all later work is uncommitted. The repository sits in a OneDrive folder (one file was truncated during validation); Chroma indexes must live outside it. `evaluation/results/` is git-ignored, so evaluation outputs (including the Qwen runs and the retrieval cache) are local only. *Decision (open)*: whether to version them.

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

### In progress
- Housekeeping: commit the work, keep this file current.
- Table retrieval quality and table spacer columns (known issues).

### Planned (next first)
15. **Stronger-model evaluation** (next): validate or replace the NLI judge with hand labels; decide the governing thresholds; run the current OpenAI small model through the unchanged stack on the pinned retrieval cache; replay policies A / B1 / C offline on its replies and compare case by case with Qwen; then decide the grounding policy and calibrate `min_support`. Needs the team's API/privacy decision (section 9).
16. **Equation extraction without vision** (coverage assessment, F-COV-2 and E2E-12): read Equation Editor / OMML objects as text; merge fragmented PDF formula lines.
17. **Figure-question benchmark** on the content that needs it (Section 02, the SPE_l1 chart, hard_PDF_1, a few AOP diagrams; about 30-40 questions), Phase 0 baseline scored first. Annotation can start in parallel with 15.
18. **Vision bake-off** (decision on a Vision LLM for figures): only on the benchmark of 17, requiring a measurable gain over Phase 0 (see `phase0_report.md` section 5); needs the team's answers on GPU, privacy and budget (`multimodal_ingestion_design.md` sections 12 and 14).
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

## 9. Answer Layer: MVP built, evaluated once, next steps

Goal: turn `RetrievalResult` into grounded, cited, refusable answers, independent of the LLM vendor. **All components below exist** (section 3.10, `answer_layer.md`); the table keeps the original plan for reference. What remains: a real-model evaluation exists for Qwen2.5-3B only, and its criteria were not met (section 11). Next: a trustworthy faithfulness measurement, a stronger model, a grounding-policy decision, then an HTTP endpoint, multi-turn history, rate limits, cost accounting and ToC-chunk handling.

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

**Next experiment (prepared, not run).** Exact commands: [`real_model_eval_report.md`](real_model_eval_report.md) section 9. *Decisions (open)* before running it: (1) the team agrees that the evaluation corpus (public sample files plus the team's own proposal and lecture PDFs) may be sent to the OpenAI API; (2) which OpenAI model: recommended first `gpt-4.1-mini` (runs through the unchanged adapter at temperature 0; reportedly leaves the API on 2027-01-14, so a diagnostic run); the successor gpt-6-luna reportedly rejects `max_tokens` and `temperature: 0`, which the adapter sends, so it needs an adapter change first; (3) which thresholds govern (eval plan vs architecture NFR-AIQ). *Hypothesis* (not a measurement): a model that reliably emits `[S#]` tags should lose far fewer answers to the citation rule than Qwen2.5-3B.

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
- **Real-LLM answer quality**: measured on Qwen2.5-3B only; pre-registered criteria not met (correctness below 0.70; faithfulness not measurable with the current judge); no stronger model tested. **Quizzes, adaptive learning** (not started).
- **Backend API, auth, multi-user data model, frontend** (skeleton or empty).
- **Upload limits and abuse protection**, **Docker/deployment**, **CI/CD**, **dependency pinning**.
- **Arabic / multilingual** content.
- **Version control hygiene**: work after commit `1660115` is uncommitted.

Verdict: the data, retrieval and answer-layer machinery (scoping, citations, refusal, grounding) are in place and tested. What is unproven is answer quality with a production-grade model: the only real model tested (3B) answers 56% (40/72, re-scored 2026-11-15) of answerable questions correctly under the shipped policy, and the faithfulness measurement is not yet trustworthy. The system as a whole is not production-ready.

---

## 11. Real-model evaluation of the Answer Layer (Qwen2.5-3B, 2026-10-25; re-scored 2026-11-15)

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

---

## 12. Changelog of this file

- **2026-11-15 corpus coverage assessment** (docs only, no code change): §6 new subsection with measured composition, reach by channel, Phase 0 per-file verdicts and labelled estimates; §3.8 real-corpus reach note; §7 open findings F-COV-1 to F-COV-4; §8 planned order changed to stronger-model evaluation -> equation extraction -> figure-question benchmark -> Vision bake-off (Gemma and later items renumbered 19-29). Full assessment in `multimodal_ingestion_design.md` section 14.
- **2026-11-15 consolidation pass** (no behaviour change to the product): header date and accurate commit state; full related-documents list; schema references 2.0 -> 2.1 (§2, §3.1); §3 subsections reordered 3.1-3.11; §3.9/§4 evaluation harness and folder tree match the repository; §3.10 status records the Qwen2.5-3B evaluation and policy A as the production default; §5 chunk-ID decision updated to chunker 1.3.0 (`c-{hash12}` / `p-{hash12}`), grounding-policy row added; §6 quality gates re-run and recorded with commands; §7 answer-layer issues rewritten from real-model evidence (judge limits, latency, list-citation property, gold limits) and version-control bullet corrected; §8 Qwen evaluation and evaluation hardening completed, stronger-model experiment next; §9/§10 updated to the measured state; appended evaluation section integrated as §11 with re-scored numbers and the a30/x09 corrections; status labels (measured / decision / hypothesis / superseded) introduced. Four design documents received superseded-status banners; `figma_ui_context.md.md` renamed to `figma_ui_context.md`.
- 2026-10-25: real-model evaluation appended (now §11).
- 2026-10-19: answer layer MVP, E2E-08, FigureDescriber plug-in point.
- 2026-10-18/19: validation phase, 30-file end-to-end validation, Phase 0.

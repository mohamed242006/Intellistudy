# Phase 0 report: E2E-07, E2E-10 and the figure infrastructure

Date: 2026-10-19 · Scope: the three items requested after the multimodal design review. No Vision LLM was used or added.
Status of the quality gates after this pass: **665 tests pass at that time** (superseded: 739 after the answer-layer pass; E2E-08 has since been fixed, see answer_layer.md), Ruff clean, MyPy clean (47 files), coverage 93% line+branch. Nothing is committed.

Every number below comes from a command in section 6; "in-sample" marks numbers measured on the data the parameters were fitted on.

---

## 1. E2E-07: slide titles typed in plain text boxes (fixed)

`ai/ingestion/pptx_reader.py` (`_infer_title`). When a slide has no title placeholder, the text box with the clearly largest explicit font size becomes the title if it is at least 18 pt, short (<= 12 words, <= 100 characters), not numeric, not ending in a full stop, and no other title-like box ties with it. Anything ambiguous gets no heading.

| Deck | Headings before | after |
|---|---|---|
| University Admission Slides | 0 | 11 |
| SlideEgg Research University | 0 | 15 |
| University Research Poster | 0 | 3 |

Tests: `tests/test_e2e_findings.py` (the former expected failure now passes; three new negative tests: tie, small/numeric/sentence text, title placeholder still wins).

## 2. E2E-10: retrieval threshold, reranking, bibliography ranking (fixed, with measured evidence)

### What was built (`ai/retrieval/`)
- `references.py`: detects bibliography chunks (heading names, or mostly `[n] Author` lines) and queries that really ask about sources. Bibliography chunks are ranked after body text unless the query asks for sources (`include_references` None / True / False).
- `rerank.py`: optional cross-encoder second stage (`cross-encoder/ms-marco-MiniLM-L-6-v2`), lazy, with graceful degradation if it fails.
- `assessment.py` + `calibration.py`: `result.assessment` = strong / weak / none **advice** from four signals (vector score, reranker score, margin, lexical coverage of the question's words) and the question words found nowhere in the hits (`missing_terms`). The policy records the models it was calibrated for; with a different embedder or reranker it is not applied silently (warning, or no assessment).
- `evaluation/`: 87 hand-labelled queries (53 answerable, 24 unrelated, 10 near-miss: on-topic but the fact is absent), an index builder, and a runner that compares strategies and calibrates with a two-fold split.

### Measured (corpus: 30 files, 1,053 chunks)

| Strategy | hit@1 | hit@3 | hit@5 | MRR@5 | answerable queries whose top hit is a bibliography | s/query (CPU) |
|---|---|---|---|---|---|---|
| baseline (vector only) | 0.849 | 0.925 | 0.925 | 0.884 | 1 | 0.45 |
| + bibliography demotion | 0.868 | 0.925 | 0.925 | 0.893 | 0 | 0.10 |
| + cross-encoder rerank | 0.887 | 0.943 | 0.962 | 0.917 | 0 | 2.5 |

Refusal signals: unrelated queries score at most -6.33 on the reranker, answerable ones at least -5.31 (a clean gap); with vector scores alone the ranges overlap (0.59 vs 0.57). Shipped policy on the 87 queries (**in-sample**): all 24 unrelated queries "none"; 46 answerable "strong", 7 "weak", 0 refused; near-miss 6 of 10 "none", 4 "weak". Cross-validated (fit on half, test on the other half): answerable passed 96-100%, unrelated refused 100%, near-miss refused 40%, "strong" precision 0.89-0.96.

### Honest reading
- The set is small: differences of a few points are one or two queries. The reranker's gain in ranking is modest; its real value is the clean refusal signal.
- The bibliography problem barely showed in the first query set; two observed failures (`What is an almost Gorenstein ring?`, `What is the injective dimension of the conormal module?`) were added verbatim as regression queries.
- Near-miss questions are only partly refused by retrieval. The answer layer must still check that the retrieved text supports the answer; `missing_terms` is there to help it.
- Reranking costs about 2.5 s per query on this CPU with 20 candidates; fewer candidates or a GPU are the levers.
- `RetrievalService.search(assess_relevance=None)` assesses automatically only when a calibrated policy applies to the configured models.

## 3. Phase 0 figure infrastructure

### Schema 2.1 (additive) and where it lives
| Piece | File |
|---|---|
| `BlockType.FIGURE`, `FigureData`, `PageContent.figures`, `PageContent.size`, image statistics on `ImageData` | `ai/ingestion/models.py` |
| Caption parsing, PDF detection (raster + vector clusters), caption pairing, citing-sentence linking | `ai/ingestion/figures.py` |
| Image Selection Layer | `ai/ingestion/figure_selection.py` |
| PDF integration (detect per page, select per document, take caption/labels out of the running text) | `ai/ingestion/ingestion_pipeline.py` |
| PPTX integration (picture + caption text box + alt text; chart values) | `ai/ingestion/pptx_reader.py` |
| DOCX integration (picture + caption paragraph) | `ai/ingestion/docs_reader.py` |
| `figure` chunk kind, citation `p. 7 > ... > Figure 3`, figure metadata | `ai/chunking/{atoms,builder,models}.py` (chunker 1.2.0) |
| Benchmark | `evaluation/figure_benchmark/` |

Design points that matter:
- **Source text stays separate from generated text.** A figure keeps `caption`, `inner_text` (native text inside a vector figure), `ocr_text`, `alt_text`, `mentions` (sentences elsewhere that cite it) and an empty `description` reserved for a later model. The chunk template labels each part; Phase 0 never produces generated text.
- **Caption detection** requires punctuation after the number (or a bold label): "Figure 3: ..." is a caption, "Figure 3 shows ..." is a sentence.
- **Vector figures** are found by clustering drawing operators; short labels hugging the cluster (tick labels, legend) become `inner_text` and leave the body text. A chart's gridlines and legend that pdfplumber reads as a nearly empty "table" no longer suppress the figure and the phantom table is dropped.
- **Selection** (hard rules, then caption, then a small fitted model) is documented in the module docstring. Large pictures repeated on slide "builds" keep only the first occurrence; small repeated pictures are template furniture.
- **Chunking:** a figure is one isolated chunk, clipped to fit (caption, text in figure, up to two citing sentences). If a figure has no text at all there is no block (nothing to retrieve) but the figure record is kept for a later description.
- PPTX chart blocks now include the plotted numbers (`Data: Q1: Model A 0.82, ...`).

### Benchmark 1: hand-labelled real candidates (236 candidates in 6 PDFs and 9 PPTX decks, 54 keepers)
Labels in `evaluation/figure_benchmark/real_annotations.json` were written by looking at every candidate (contact sheets). Pictures under 64 px are not annotated (hard rule).

| | precision | recall | tp / fp / fn |
|---|---|---|---|
| all | 0.76 | 0.83 | 45 / 14 / 9 |
| PDF (lecture slides, a physics paper) | 0.73 | 0.90 | 27 / 10 / 3 |
| PPTX (9 decks) | 0.82 | 0.75 | 18 / 4 / 6 |

These are **in-sample** (the model was fitted on these labels). The honest generalisation estimate is the leave-one-file-out result for uncaptioned candidates (227 candidates, 50 figures): precision about 0.68, recall about 0.82. The first rule-based version scored recall 0.17 (it kept almost nothing without a caption), which is why the model exists. Remaining errors are semantic: code screenshots, text fragments rendered as images and template title pictures look like diagrams to cheap pixel statistics.

### Benchmark 2: synthetic papers with exact ground truth (6 PDFs, 12 charts, 36 questions)
| Detection | |
|---|---|
| figures found with the right label and page | 12 / 12 |
| raster vs vector classified correctly | 12 / 12 |
| caption text exact | 12 / 12 |
| citing sentence linked | 12 / 12 |
| false positives (logos, banners, icons kept) | 0 |

| Retrieval of the 36 figure questions | hit@1 | hit@3 | hit@5 | MRR@5 |
|---|---|---|---|---|
| figures disabled (caption is a paragraph, chart is an OCR chunk) | 0.278 | 0.806 | 1.000 | 0.558 |
| Phase 0 (one figure chunk per chart) | 0.639 | 1.000 | 1.000 | 0.815 |

The corpus was written by the same team as the detector, so this shows the mechanism works on clean inputs; it is not a real-world accuracy estimate. Part of the baseline's weakness is the phantom tables it creates from chart gridlines (6 table chunks that Phase 0 no longer produces).

### Regression check on the 30 real files (figures on)
0 chunker validator problems, 0 oversize chunks. 473 candidates, 29 kept, 25 figure blocks/chunks (4 kept figures have no text yet).
Note: `statistics["image_ocr_count"]` still means "images that produced OCR text"; some of those images are now inside figure blocks, so it no longer equals the number of `image_ocr` blocks.

## 4. Limitations (known, not hidden)
- Selection is a baseline: about 1 in 3 kept uncaptioned pictures is not worth keeping (code screenshots, text slices), and about 1 in 5 real figures is missed. This is what a later triage model should improve.
- Captions that sit on the next page or a different block structure are not paired (the proposal's "Figure 1" is a caption-only figure). Multi-panel figures with one caption are merged only when panels pair with the same caption; an unmatched extra panel can be missed (`hard_PDF_1`).
- Equations as images are kept as figures but not interpreted; scanned pages are page-OCR territory, not figures.
- DOCX figure selection is unit-tested but has no hand-labelled real data (the DOCX files in the dataset are synthetic samples).
- PPTX pictures only: SmartArt, grouped vector drawings and charts-as-shapes are not detected as figures (native charts keep their structured block).
- No description exists yet: a figure without caption, OCR text, inner text or alt text is recorded but not indexed.

## 5. What this enables, and the gate for the VLM decision
Phase 0 is the baseline the design review asked for. To decide whether a Vision LLM is worth adding, run the same benchmarks with descriptions and compare: (a) retrieval of figure questions on a benchmark that includes figures whose meaning is not in the caption (the synthetic set answers questions the caption already contains), (b) factual accuracy and hallucination of descriptions against the exact data of the synthetic charts, (c) cost and latency. The synthetic generator already stores the true values and the winning model of every chart for (b). Before that, the real-figure benchmark should grow (more annotators, DOCX, figures with captions in the middle of slides).

## 6. Reproduce
```
python -m unittest discover -s tests -t .                                  # 665 tests
python -m evaluation.index_builder                                         # once; embeds the 30-file corpus (slow)
python -m evaluation.retrieval_eval --strategy all --calibrate --assess    # E2E-10 numbers
python -m evaluation.figure_benchmark.detection_eval --show-errors         # real-label detection
python -m evaluation.figure_benchmark.figure_eval                          # synthetic detection + retrieval
python -m evaluation.figure_benchmark.contact_sheets <pdf> <out_dir>       # label more candidates
```

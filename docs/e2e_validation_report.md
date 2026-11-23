# IntelliStudy - End-to-End Validation Report (30-file dataset)

Date: 2026-10-18 · Scope: `data/uploads/docs` (10 DOCX), `data/uploads/PDFs` (10 PDF), `data/uploads/pptx` (10 PPTX).
Pipeline under test: ingestion (+OCR, normalisation, canonical schema) -> chunking (+parent-child) -> BGE embeddings -> ChromaDB (+SQLite parents) -> retrieval -> re-ingestion.
Method: failures were identified first and reproduced as failing tests, then fixed. Findings that are reported but not fixed are kept as `expectedFailure` tests (`tests/test_e2e_findings.py`, class `OpenFindings`).

## 1. Result in one paragraph

All 30 files ran through every layer (the three `spytm_*` files are 1-10 MB padding files holding 3 real paragraphs each). Ingestion, chunking, indexing, scope filters and re-ingestion are consistent: zero chunker validator problems, zero oversize chunks, zero duplicate or orphan chunk ids, every stored vector matches its chunk metadata, no scope leaks in 5 user/course combinations, and re-ingesting the identical file reproduced identical chunk ids for 30/30 files (29 of them re-indexed with 0 chunks embedded). The run found **6 defects (all fixed)**, plus **6 open findings**. Retrieval of auto-generated queries scored recall@1 0.62 / recall@5 0.81 over 946 queries; the weak spots are math-heavy PDFs and synthetic filler documents (see 5).

Test status after fixes: **598 tests pass** (6 skipped, 4 expected failures = 3 open findings + Arabic order), Ruff clean, MyPy clean (41 files), 10 routing tests pass. 12 new tests added.

## 2. Files tested

| file | unit | blocks | headings | tables | OCR images | chunks | parents | queries | R@1 | R@5 |
|---|---|---|---|---|---|---|---|---|---|---|
| docs/sample-5mb.docx | doc | 27,605 | 1 | 0 | 0 | 13,248 | 3,253 | 40 | 0.15 | 0.30 |
| docs/sample-docx-files-sample1.docx | doc | 88 | 17 | 5 | 0 | 16 | 8 | 38 | 0.87 | 0.97 |
| docs/sample-docx-files-sample4.docx | doc | 601 | 0 | 0 | 1 | 402 | 90 | 40 | 0.07 | 0.23 |
| docs/sample-files.com-image-document.docx | doc | 31 | 8 | 1 | 0 | 8 | 7 | 22 | 0.91 | 1.00 |
| docs/sample-files.com-large-document.docx | doc | 460 | 109 | 29 | 0 | 97 | 85 | 40 | 0.85 | 0.95 |
| docs/sample-long.docx | doc | 92 | 19 | 0 | 0 | 36 | 19 | 40 | 1.00 | 1.00 |
| docs/spytm_Medium_{1,5,10}MB.docx | doc | 3 each | 1 | 0 | 0 | 1 each | 1 each | 3 each | 1.00 | 1.00 |
| docs/test1word.docx | doc | 3 | 0 | 0 | 1 | 3 | 1 | 2 | 1.00 | 1.00 |
| PDFs/hard_PDF_1..10.pdf | 4-24 pp | 66-922 | 1-17* | 0 | 0-3 | 8-58 | 3-19 | 24-40 | 0.35-0.65 | 0.55-0.88 |
| pptx/Physiotherapy ... Musculoskeletal | 56 sl | 294 | 46 | 3 | 4 | 47 | 44 | 40 | 0.72 | 0.93 |
| pptx/Physiotherapy ... Pathophysiology | 55 sl | 288 | 49 | 3 | 3 | 44 | 42 | 40 | 0.62 | 0.90 |
| pptx/SPE_l1.pptx | 86 sl | 757 | 18 | 1 | 1 | 68 | 67 | 40 | 0.82 | 1.00 |
| pptx/Section 01 - Introduction | 27 sl | 158 | 27 | 3 | 5 | 28 | 25 | 40 | 0.88 | 1.00 |
| pptx/Section 02 - Classical Encryption I | 17 sl | 82 | 16 | 8 | 8 | 25 | 15 | 40 | 0.97 | 1.00 |
| pptx/Section 03 - Classical Encryption II | 21 sl | 149 | 20 | 19 | 1 | 41 | 20 | 40 | 0.68 | 0.88 |
| pptx/SlideEgg Research University | 16 sl | 112 | **0** | 0 | 0 | 14 | 14 | 23 | 0.91 | 1.00 |
| pptx/Statistical Methods ... Biostatistics | 56 sl | 311 | 50 | 3 | 1 | 44 | 42 | 40 | 0.78 | 0.93 |
| pptx/University Admission Slides | 13 sl | 82 | **0** | 0 | 0 | 13 | 13 | 22 | 0.91 | 0.95 |
| pptx/University Research Poster | 3 sl | 44 | **0** | 0 | 2 | 3 | 3 | 6 | 1.00 | 1.00 |

Totals: 36,128 blocks, 14,542 chunks, 3,877 parents, 946 retrieval queries. *PDF headings counts are from the final run; `hard_PDF_2` has since risen from 1 to 20 after the E2E-06 follow-up (verified by re-ingesting).
Hidden slides and charts: none exist in this dataset (those features are covered by synthetic tests only). Because embedding is slow on this machine (~5 chunks/s), `sample-5mb.docx` was fully ingested and chunked (13,248 chunks, determinism verified on all of them) but only its first 600 chunks were embedded and queried.

## 3. Results per step

| Step | Check | Result |
|---|---|---|
| 1 Ingestion | page / slide numbering, source metadata, stats consistency, blank / control chars, tables, images | numbering and metadata correct for 30/30; after fixes no blank blocks, no private-use glyphs |
| 2 Canonical structure | ordering, duplicates, heading hierarchy | `order` = 0..n-1 and pages monotone in 30/30; heading `path[-1] == text` always; adjacent duplicate blocks are genuine repeated content (lorem ipsum, template placeholders, repeated math labels) |
| 3 Chunking | validator, stable ids, parent links, heading_path, tables, OCR, citations | 0 validator problems, 0 oversize, 0 orphans; re-chunking is deterministic; all table cells present in table chunks; OCR confidence = min of block confidences and `low_confidence` consistent; citations start with the right `p. N` / `slide N` |
| 4 Embeddings | success, duplicate vectors, hash stability | all vectors 384-d, finite, unit norm; vectors shared only by chunks with identical embedding text (392 in `sample4.docx`, which repeats the same paragraphs) |
| 5 ChromaDB | metadata, user / course filters, parent refs | stored metadata equals chunker metadata for every chunk; parent store holds exactly each document's parents; 0 leaks across u1/c1, u2/c1, u1/c2, unknown user, unknown course; `kind` filter exact |
| 6 Retrieval | accuracy, parent expansion, citation integrity | hits equal their chunks (label, page, path, slide, text, kind; OCR confidence rounded to 3 dp by design); every hit has a parent that contains it; see 5 for accuracy |
| 7 Re-ingestion | same file; edited file | same file: 30/30 identical ids, 0 embedded. Edited files (6 real files: text edited, paragraph / slide removed): no stale or duplicate vectors, parents consistent, new text retrievable (5/6), removed text gone (6/6), unchanged text reused without re-embedding. All chunk ids change on edit (open finding E2E-08) |

## 4. Issues

### Fixed (each has a failing-first test in `tests/test_e2e_findings.py`)

| ID | Sev | Finding | Root cause | File | Fix | Test |
|---|---|---|---|---|---|---|
| E2E-01 | Major | In `large-document.docx` 23 section headings (2.1, 3.1, 6.2 ...) appeared in no chunk; citations and embeddings named only the document title | small sibling sections are merged and `heading_path` shrinks to the common ancestor; the lost titles were only in a metadata field | `ai/chunking/builder.py` (`_merge`) | the merged chunk now carries each section's title line in its text and embedding | `E2E01MergedSectionsKeepTheirTitles` |
| E2E-02 | Minor | table cell `a|b` / `cat|dog` stored as `a/b` / `cat/dog` | pipe replaced by `/` when rendering markdown | `ai/chunking/render.py:13` | pipe escaped as `\|` | `E2E02TablePipeCharacterIsPreserved` |
| E2E-03 | Major | Symbol-font glyphs reached chunks as private-use characters (`M/M/c/<box>/N`): 134 blocks in `SPE_l1.pptx`, 64 in `hard_PDF_2/5/6/9` (big-brace and parenthesis pieces) | no mapping for U+F0xx (Symbol font) and U+F8xx (Adobe Symbol pieces) | `ai/ingestion/cleaners.py` | unambiguous Symbol codes mapped to Unicode math (infinity, arrows, Greek, brace pieces); Wingdings bullet codes left alone | `E2E03SymbolFontGlyphsAreMapped` |
| E2E-04 | Minor | 4 empty table blocks on slides 46/47 of three Slidesgo decks | decorative all-empty tables were emitted | `ai/ingestion/pptx_reader.py` (`_extract_tables`) | tables with no text are skipped | `E2E04EmptyTablesAreNotBlocks` |
| E2E-05 | Major | in 9 of 10 PDFs the rotated margin stamp `arXiv:2610...` (20 pt) was a level-1 heading and the root of every chunk's heading_path / citation | rotated text was treated like horizontal text | `ai/ingestion/pdf_reader.py` (`_collect_lines`) | rotated lines are dropped when horizontal text dominates the page | `E2E05RotatedMarginStampIsNotAHeading` |
| E2E-06 | Major | the 10 PDFs had 1-2 headings (title + stamp) although every one has a bookmark outline; sections ("1. PRELIMINARIES", "REFERENCES") were paragraphs | outline was only used to re-level existing headings; small-caps titles are body-sized; bookmarks lack the section number | `ai/ingestion/structure.py` (`apply_outline_levels`) | a paragraph equal to a bookmark title on that page (numbering optional) becomes a heading; `hard_PDF_2` 1 -> 20 headings | `E2E06OutlineEntriesBecomeHeadings` (3 tests, including a negative one) |

Self-inflicted and caught by Ruff: E2E-01's first version used `Block` without importing it (F821); fixed.
Also updated one old test (`test_chunking.TableEdgeTests`) that asserted the old `a/b` behaviour.

### Open (reported, not fixed; reproducible as expected-failure tests where possible)

| ID | Sev | Finding | Root cause / file | Recommended fix | Test |
|---|---|---|---|---|---|
| E2E-07 | Major | 3 of 10 decks have 0 headings (`University Admission Slides`, `SlideEgg Research University`, `University Research Poster`): titles are plain text boxes, so chunks are cited only as `slide N` and embedded without a topic | `ai/ingestion/pptx_reader.py` only accepts title placeholders | when no title placeholder exists, use the top-most / largest-font text box as the slide title | `OpenFindings.test_e2e07...` |
| E2E-08 | Minor (design) | after editing a file every chunk id changes (surviving ids 0% in 6 real edits); vectors are still reused (e.g. 11 of 12 reused) so cost is low, but anything keyed to chunk ids (stored citations, feedback) breaks | ids embed the file hash `doc_id`: `ai/chunking/ids.py::make_chunk_id` | derive ids from the stable `document_uid` and content hash instead of the file hash | `OpenFindings.test_e2e08...` |
| E2E-09 | Minor | a merged DOCX chunk is cited with the common ancestor only (`Sample Large Multi-Section Document`) although its text now starts with the real section title | `ai/chunking/builder.py::_finalise` builds the label from the shrunk `head_path` | cite the first section's full path, or add `(+N sections)` | `OpenFindings.test_e2e09...` |
| E2E-10 | Minor | retrieval ranking: no default score floor (unrelated queries score 0.49-0.68); reference lists can outrank the abstract ("almost Gorenstein ring" -> References 0.79 vs abstract 0.77); dense-math chunks give weak recall (0.35-0.65 @1) | `ai/retrieval/service.py` (`min_score` is optional); BGE-small on formulas | calibrate a threshold or re-rank; down-weight or flag bibliography sections; later a stronger embedder | none (needs labelled set) |
| E2E-11 | Minor (performance) | chunking a 27,605-block DOCX took 104-137 s; ingestion 17-29 s | linear, dominated by ~97k tokenizer calls of ~1 ms (`ai/chunking/tokens.py::HFTokenCounter.count`) | batch / memoise token counts | none |
| E2E-12 | Minor | equation fragments become standalone paragraph blocks (`a=1`, `Φ′`, `kUV`, brace pieces) in math PDFs | PyMuPDF line splitting of typeset math (`ai/ingestion/pdf_reader.py`) | merge short fragments into the neighbouring paragraph | none |

Operational notes (not defects): embedding runs at ~5 chunks/s on this CPU, so a 13k-chunk document needs well over 30 minutes; production needs a background job queue and upload limits. Chroma indexing of 3,000 chunks measured 16.5 s earlier in the performance suite.

## 5. Retrieval detail

Auto-generated queries (up to 40 per file): first sentence of a chunk, rare keywords, heading + topic, table keys. Mean recall@1 / @5 = 0.62 / 0.81 (DOCX 0.64 / 0.73 including two synthetic filler files, PPTX 0.80 / 0.95, PDF 0.44 / 0.72).
- By query type, recall@1: heading+topic 0.42 (PDF) / 0.90 (DOCX) / 0.86 (PPTX); keywords 0.40 / 0.42 / 0.87; sentence 0.51 / 0.72 / 0.71; table keys 1.00 (DOCX) / 0.60 (PPTX).
- Why the low rows are not simple bugs: `sample-5mb.docx` and `sample4.docx` contain random strings or the same paragraphs hundreds of times (the right answer is ambiguous by construction); the math PDFs produce auto-queries that are cut formula fragments, and the misses are usually neighbouring chunks of the same section.
- Manual check: 20 natural-language questions across the PDFs, PPTX and DOCX; 15 returned a directly relevant chunk first with the right citation (for example "Is K-injectivity a local property?" -> `p. 13 > 3. THE LOCAL NATURE OF K-INJECTIVITY`; "How does the Playfair cipher work?" -> `slide 10 > Playfair Cipher`). The 5 weaker ones were: a bibliography outranking the abstract (E2E-10), three template or content-free decks (Slidesgo x2, Admission), and "What is an inline image?" returning wrapping sections instead of the inline-image section.
- One re-ingestion check did not retrieve the added sentence first (`hard_PDF_4.pdf`): the sentence is present as a block and chunk, but is one line inside a dense math chunk (E2E-10).

## 6. Not verified

- Hidden slides, charts and low-confidence OCR chunks (absent from the dataset; synthetic tests only).
- Full embedding of the 13,248-chunk document (first 600 only).
- Automatic queries are a proxy; there is no human-labelled evaluation set.
- The harness itself had two issues that were fixed during the run (Windows path length for result files; empty generated queries, which the service correctly rejects).

## 7. Readiness

Ingestion, chunking, storage, scoping and re-ingestion are ready for the RAG answer layer. Before relying on citations: fix E2E-07 (slide titles) and decide E2E-08/E2E-09 (id stability, merged citations). The answer layer must own the score threshold / re-ranking (E2E-10).

---
## Addendum 2026-10-19
E2E-07 (PPTX text-box titles) and E2E-10 (retrieval thresholds, reranking, bibliography ranking) are fixed; see [phase0_report.md](phase0_report.md). E2E-08 (chunk id stability) was fixed afterwards, see [answer_layer.md](answer_layer.md). E2E-09, E2E-11 and E2E-12 remain open.

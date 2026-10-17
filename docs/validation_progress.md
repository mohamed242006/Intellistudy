# Validation phase: progress checkpoint

Paused by the user mid-task. Resume from "NEXT STEP" when told to continue.

## Task
Final quality/reliability validation before the RAG answer layer: a comprehensive test suite (unit, integration, regression, edge, failure, performance, data-integrity), then Ruff, MyPy, static analysis, coverage, and a final strict production-readiness report (coverage report, missing coverage, critical bugs, recommended fixes, readiness verdict). Existing tests must not be overwritten.

## Tooling installed (global Python 3.12)
ruff 0.17.1, mypy 2.4.0, coverage 7.16.2, vulture 2.16, chromadb 1.5.9, sentence-transformers 6.0.0. `pyproject.toml` created (ruff/mypy/coverage config).

## Baseline (before this phase)
334 tests, 90% line+branch coverage. Ruff: 45 findings (2x F821 undefined name in tests/test_chunker.py, 4x B023, 7x B905, unused imports, etc.). MyPy: 14 errors in 6 files (structure.py, pdf_reader.py, models.py, ocr_processor.py import-untyped, chroma_store.py configuration type, ingestion_pipeline.py). Vulture: only dead code is a false positive (table_extractor `__exit__` args) plus unused-by-design helpers.

## New test files written (all passing unless noted)
- tests/random_docs.py (seeded random documents), tests/chunk_fixtures.py (shared)
- tests/test_chunking.py (44), tests/test_ingestion.py (46, 1 expected failure = Arabic order), tests/test_embeddings.py (30), tests/test_chroma.py (23), tests/test_reingestion.py (42), tests/test_retrieval_edge.py (16)
- tests/test_data_integrity.py (8): **4 failures in `test_everything_stored_matches_the_chunker_output_for_random_documents`**, see "Open item".

## Real defects found and FIXED
1. Hard 480-token limit violated by oversize single list item, table row, many-column row, chart, long heading prefix (atoms.py, builder.py prefix cap + fitting).
2. Concurrent PDF ingestion on a shared pipeline corrupted text and tables (3 of 4 docs). Fixed with a lock in `IngestionPipeline._ingest_pdf`; test verified to fail without it.
3. NaN/inf/zero vectors accepted by embedder and indexer (bge.py, indexing.py).
4. Filter values could carry backend operators; reserved scope keys (interfaces.validate_filters, both stores).
5. Invisible-only text (zero-width chars) became chunks (selection.is_blank, cleaners).
6. Validator false positive on overlap in merged chunks (own bug).
7. Stale stored metadata: a chunk with unchanged id/vector but changed parent (or page/citation) kept a dangling `parent_chunk_id` after re-ingestion. Fixed with `record_hash` + metadata refresh (models.py, indexing.py, stores).
8. Parent-store id collision between users uploading the same file (parents now keyed `document_uid:chunk_id`).
9. Unbreakable tokens (base64/URLs) could produce oversize chunks (text._split_chars).
10. Invalid Chroma collection names for unusual model ids / 600-char ids; collisions after sanitising (config.collection_name).
11. Lone UTF-16 surrogates crashed hashing and chunking (cleaners `_SURROGATES`, ids surrogatepass).
12. Query embedding dimension not validated; in-memory cosine silently truncated mismatched vectors.
13. Identical embedding texts were embedded repeatedly within one call (now once).
Known limitation, documented as an expectedFailure test: Arabic text is extracted in visual (reversed) order by PyMuPDF.

## Incident (be honest in the final report)
A patch script truncated `ai/ingestion/cleaners.py` to 0 bytes (write failed after the file was opened). I restored it from my earlier version in full; test_cleaners, test_schema, test_pdf_quality and test_ingestion (112 tests) pass again. Lesson: patch scripts must encode content before opening for write.

## Open item (where I stopped)
`test_data_integrity.py::test_everything_stored_matches...` fails in the self-retrieval check ("a chunk's own text must retrieve it in top 5"). Debugging output showed the misses are **table-part chunks** (pipe-markdown text like `| H0 | H1 | t4r0c0 |`): the fake bag-of-words embedder scores their own text only ~0.05 against the key/value `embedding_text` that was actually embedded, so a text-vs-embedding_text mismatch, not a search defect. Decide: (a) query with the chunk's `embedding_text` body for table chunks, or (b) restrict the self-retrieval assertion to non-table chunks and add a dedicated test that tables are found by their cell values. This also hints at a real consideration: tables are embedded as `Header: value` text, so queries phrased as column/value pairs match better than raw markdown.

## NEXT STEP (when told "continue")
1. Resolve the open item above (likely option b + a cell-value retrieval test) and get tests/test_data_integrity.py green.
2. Write tests/test_edge_cases.py (surrogates, weird ids with ':' and unicode, counters returning 0 or huge values with a timeout, tiny/huge configs, engine thread-safety, long file names), tests/test_regression.py (one test per fixed defect above, esp. stale `parent_chunk_id` after a duplicated section, parent collision across users), tests/test_performance.py (budgets for chunking 200k words, indexing 3000 chunks, Chroma query latency over 5000 vectors, ingestion of 150-page PDF/3000-paragraph DOCX/150-slide PPTX, linear-scaling check, memory peak; print timings).
3. Run the complete suite; fix Ruff findings (safe auto-fixes plus F821/B023/B905), fix the 14 MyPy errors, re-run vulture.
4. Run `coverage run --branch -m unittest discover -s tests -t .` and report per-module coverage, remaining gaps (pptx_reader/docs_reader/pdf_reader branches, ingestion_pipeline paths).
5. Final report: coverage, missing areas, critical bugs (list above), recommended fixes, production-readiness assessment (strict). Mention remaining known gaps: no upload size/page limits, English-only, Arabic order, single-process Chroma, no PostgreSQL yet, nothing committed.

---
## STATUS: COMPLETE (2026-10-18)
All NEXT STEP items done. Final state: 584 tests pass (6 skipped = opt-in real-model/tooling, 1 expected failure = Arabic logical order) + 10 routing tests; coverage 93% line+branch (baseline 90%); Ruff clean; MyPy 0 issues in 41 source files.
Additional defects fixed during the final pass: DOCX/PPTX text bypassed `clean_text` (now normalised like PDF), invisible/bidi characters had leaked into test sources (all converted to visible escapes), `cleaners.py` restored after the truncation incident.
Commands: `python -m unittest discover -s tests -t .` | `python -m coverage run -m unittest discover -s tests -t . && python -m coverage report` | `python -m ruff check ai tests` | `python -m mypy ai`. Slow tests: set `INTELLISTUDY_SKIP_SLOW=1`; real-model tests: `INTELLISTUDY_MODEL_TESTS=1`.

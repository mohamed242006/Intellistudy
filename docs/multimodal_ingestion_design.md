# Design Review: Multimodal Figure Understanding for IntelliStudy

Status: PROPOSAL. **Update 2026-10-19: Phase 0 (no VLM) is implemented and benchmarked, see [phase0_report.md](phase0_report.md); the VLM phases below remain proposals.** **Update 2026-11-15: a measured corpus-coverage assessment (section 14) finds that Vision is not currently the highest-priority gap; equation extraction comes first.** · Date: 2026-10-18 · Audience: the four-person team and supervisor deciding scope before the RAG Answer Layer.
Conventions: **[measured]** = observed on this repository or dataset; **[assumption]** = my estimate, to be replaced by a benchmark before any commitment. Model and price details are not verified here and must be re-checked when a model is chosen.

---

## 0. Summary and recommendation

1. The gap is real but narrower than it looks. OCR already turns text inside images into chunks (`image_ocr`), and PPTX native charts already become structured `chart` blocks. What is missing is (a) figures that have no embedded text, (b) the *meaning* of a figure (what is compared, what the trend is), (c) figures drawn as vector graphics, which the current extractor cannot see at all.
2. **Do not start with a Vision LLM.** Phase 0 ("figure-aware text") links each figure to its **caption**, its **OCR text** and the **paragraphs that cite it** ("as shown in Fig. 3"). In papers, the caption plus the citing sentence usually carries the conclusion the user is asking about. It costs no model, is deterministic, and gives the baseline against which a VLM must prove its worth.
3. Add the VLM as an **asynchronous enrichment step behind an adapter**, on a **small, selected set of figures**, with output clearly labelled as generated. MVP = Phase 0 + selection layer + one VLM + `FigureBlock` + a `figure` chunk kind.
4. Priority (details in section 11): **E2E-07 -> E2E-10 -> multimodal MVP -> E2E-12**, with E2E-08 (chunk-id stability) done before enrichment ships, because enrichment rewrites chunks.
5. Biggest unknowns, none answerable without a decision from you: where the VLM runs (the dev machine is CPU-only), whether user documents may be sent to an external API, and the per-document cost budget. See section 12.

---

## 1. What exists today (evidence)

**Current image handling** [measured from code]
- PDF: `PDFReader.extract_images` lists raster images (`ImageData`: xref, size, bbox, OCR fields; no pixels kept). OCR runs per image with filters (too small/thin, no text, low confidence); repeated images (logos) are blanked by `repeated` detection. Result: `image_ocr` blocks with `confidence`.
- DOCX/PPTX: shared `image_ocr.py`; PPTX caches OCR by image sha1, skips EMF/WMF (mild score 0.70). PPTX native charts become `chart` blocks (title, axes, categories, series, legend; **values not extracted**).
- Chunking: `image_ocr` is an isolated atom (own chunk); OCR confidence < 0.3 dropped, < 0.6 flagged. PPTX title-only slides are not indexed.

**What the validation dataset can and cannot tell us** [measured, this session]

| Material | Raster images (>=64 px) | Pages with vector drawings (>=20 paths) | "Figure N" caption lines | Reading |
|---|---|---|---|---|
| hard_PDF_2..10 (arXiv math) | 0 | 0-1 | 0 | text and equations only |
| hard_PDF_1 (physics) | 3 | 2 of 13 | 4 | the only real figure paper |
| Aspect-Oriented lecture PDFs | 20 / 16 | 2 / 3 | 0 | diagrams and code screenshots, no captions |
| Intellistudy proposal | 0 | 9 of 22 | 1 | **diagrams are vector drawings** |
| SPE_l1.pptx | 230 pictures, 54 OLE/graphic frames | - | - | many are icons/equations |
| Slidesgo decks | 11-13 pictures but 781-1,003 grouped shapes | - | - | decorative vector clutter |
| Native PPTX charts | 0 in all 10 decks | - | - | the structured chart path is untested on real data |

Three consequences:
- **Vector figures are invisible today.** The proposal's architecture diagrams (9 pages with drawings, 0 images) produce no block at all.
- **The dataset is too thin to validate any of this.** A new benchmark is required (section 9).
- Heavy decorative vector content in PPTX means "has shapes" is a useless signal for importance.

---

## 2. Where image understanding fits in the pipeline

```
 file -> Reader (text, tables, images, vector regions)
       -> [NEW] Figure Detection   (find figure regions + captions + in-text references)   deterministic
       -> [NEW] Image Selection    (score, keep / skip / budget)                           deterministic, cheap
       -> OCR (existing, on kept figures)                                                  existing
       -> DocumentBuilder / finalize -> Document with FigureBlock (description EMPTY)      FAST PATH, upload returns
 ...
       -> chunking -> embeddings -> Chroma   (figure chunk = caption + OCR + citing text)  usable immediately
 ...
       -> [NEW] Figure Enrichment job (VLM) -> fills FigureBlock.description
       -> re-chunk the figure chunk only -> existing re-ingestion path (embedding_hash/record_hash) -> re-embed 1 chunk
```

Decisions:
- **Two-phase, not inline.** A VLM call is seconds to tens of seconds; blocking ingestion on it would make a 36-page lecture deck take minutes and couple upload success to a model server. Phase A (caption + OCR + citing text) is searchable immediately; Phase B improves the chunk later. The existing re-ingestion machinery already supports "same block, better content": only the figure chunk's `embedding_hash` changes, so one vector is re-embedded and the rest are `unchanged`.
- **Detection belongs in the readers, selection after.** Readers know the format (PDF bbox, PPTX shape tree, DOCX anchors); selection should be one format-independent module scoring a common `FigureCandidate` record, so rules are tested once.
- **Not in the chunker.** The chunker consumes blocks; it must not call models. This keeps chunking deterministic (current guarantee: same input -> same ids).
- **Adapter boundary** `FigureDescriber.describe(image, context) -> FigureDescription` mirrors the planned `LLMClient`, so the VLM can be local, hosted, or a stub in tests.
- **PDF vector figures:** detect with `page.get_drawings()` clustering, then render the clipped region to a bitmap. Strongest cheap anchor: a caption line "Figure N / Fig. N" directly below/above a cluster or image.
- **PPTX:** prefer structure over pixels. Native charts: extract the series *values* (python-pptx exposes them) and render a table, no VLM needed. Pictures: normal path. Groups: treat a group as one candidate figure only when it contains text/connectors and is not a repeated layout element.

## 3. Should the canonical schema get a `FigureBlock`?

**Yes, add `BlockType.FIGURE`; keep `image_ocr` for backward compatibility** (schema 2.1, additive like 2.0 was).

Why not reuse `image_ocr`: OCR text, caption, generated description and provenance have different trust levels and different lifecycles (the description arrives later and is regenerated when the model changes). Packing them into one string loses that, and the citation/refusal logic of the answer layer needs to know which part is quoted source text and which is machine-generated.

Proposed fields (all optional except identity):

| Field | Purpose |
|---|---|
| `figure_id` | stable id: `{doc_id}-F{n}` plus image content hash |
| `kind` | `raster` / `vector_region` / `pptx_chart` / `pptx_group` / `docx_inline` |
| `figure_label` | "Figure 3", "Fig. 2b" parsed from the caption |
| `caption` | verbatim caption text (source text) |
| `ocr_text`, `ocr_confidence` | verbatim OCR (source text), existing scoring |
| `figure_type` | chart / graph / diagram / architecture / flow / comparison / photo / equation / other |
| `description` | generated summary (derived text) |
| `visible_numbers` | numbers the model read, to be cross-checked against OCR |
| `referenced_by` | block orders of paragraphs that cite the figure |
| `bbox`, `page_number`, `crop_ref` | location and stored crop |
| `selection_score`, `selection_reasons` | why it was kept |
| `provenance` | `{model, model_version, prompt_version, params, created_at, image_sha256}` |
| `description_status` | `none` / `pending` / `done` / `failed` / `skipped` |

Compatibility rule: an existing `image_ocr` block that is promoted to a figure is *replaced* by one `FIGURE` block carrying the same OCR text, so chunks never contain the OCR twice. `statistics` gains `figure_count`, `figure_described_count`; existing keys unchanged.

## 4. Combining OCR, caption and generated description

Principle: **keep three layers separate in storage, merge them only when rendering a chunk, and label every layer.**

1. **Caption** (author's words, highest trust) - verbatim.
2. **OCR text** (verbatim, with confidence) - labels, axis ticks, legends, numbers.
3. **Citing context** - the sentence(s) that mention "Fig. N" (author's interpretation, often the conclusion). Found by regex on figure labels; stored as references, rendered as one short excerpt.
4. **Generated description** - only qualitative structure and relationships; numbers only if they also appear in OCR/caption.

Chunk text (shown to the LLM; fixed template so retrieval and the answer layer can rely on it):

```
[Figure 3] (page 7)
Caption: <verbatim>
Text in figure (OCR): <verbatim, may be noisy>
Discussed in text: "<citing sentence>"
Generated description (AI-generated, may contain errors): <summary>
```

Embedding text = the same, with the heading-path prefix, but **without** boilerplate labels the embedder would waste capacity on; the description is truncated to a fixed budget (about 120-150 tokens) so it cannot dominate the caption.

Conflict rule: if the description contradicts the caption/OCR (for example different numbers), the description is dropped, status `conflict`, and the chunk falls back to caption + OCR. Numbers in answers must be quoted from caption/OCR/table, never from the description alone.

Required VLM output (JSON, validated; one retry; otherwise `failed`): `figure_type`, `title`, `summary` (2-3 sentences), `key_findings` (list), `entities` (series/models/axes), `visible_numbers` (verbatim), `legibility` (good/partial/poor), `uncertainty` notes. Prompt receives the caption and OCR text as *context* and is told that image text is data, not instructions (section 8).

## 5. Image Selection Layer

Goal: spend VLM calls only where meaning is lost without them. A deterministic scorer produces `selection_score` and reasons; thresholds and a per-document budget decide.

**Signals (cheap, no model)**

| Signal | Raises score | Lowers score |
|---|---|---|
| Caption "Figure/Fig./Chart/Diagram N" adjacent | strong | - |
| Cited in body text ("see Fig. 3") | strong | - |
| Size: >= ~15% of page area, >= ~300 px short side | moderate | tiny (<64 px), thin banners (aspect > ~6:1) |
| Location | inside the text flow | in header/footer bands; full-page background |
| Repetition | - | same perceptual hash on >= 3 pages or on master/layout (logos, icons, watermarks) |
| Pixel statistics | many distinct colors, line/edge structure, axis-like long lines | near-uniform, photo-only gradients, very low entropy |
| OCR | numeric tokens, short label-like words (chart-like) | no text and tiny/decorative |
| Vector clusters | many paths with text labels, arrows/connectors (diagram) | dense but text-less ornament clusters; grouped shapes repeated per slide |
| Format role | PPTX: not on layout/master, not behind text | PPTX picture marked decorative (`descr` empty + tiny + repeated) |
| Existing outcome | OCR returned label-like text | OCR "repeated" blank (already implemented) |

**Triage classifier (second stage, for ambiguous scores only):** a small image classifier or a cheap VLM prompt with a closed label set (chart, graph, diagram, architecture, flow, comparison, table-image, equation, photo, logo, decorative, other). Output is used only to keep/skip, not indexed. This keeps the expensive description call for figures that matter.

**Classes**
- Keep: charts, graphs, scientific figures, architecture diagrams, process flows, comparison visuals, screenshot-of-code/UI *only if* OCR confidence is low (otherwise OCR already works - 0.77-0.87 on the lecture code screenshots).
- Skip: logos, decorative graphics, watermarks, backgrounds, repeated icons, stock photos with no caption, isolated bullets.
- Equations as images: route to a LaTeX/OCR path later (section 11), not to the descriptive VLM.

**Budget and controls:** max figures per document (default about 30 [assumption]), ranked by score; per-course feature flag; an `always describe` / `never describe` override per figure for the user later; all decisions logged with reasons so they can be audited and tuned.

**Known hard cases to test:** multi-panel figures (a-d), figures split across two pages, rotated figures, scanned papers (the whole page is an image - this is page OCR territory, not figure territory), vector charts with live text (text is already extractable; the VLM is only needed for the relationships).

## 6. Metadata and citation strategy

Chunk metadata additions (flat, Chroma-compatible, like existing fields):
`kind="figure"`, `figure_id`, `figure_label`, `figure_type`, `source_kind` extended with `vlm_description` (existing values: native, ocr_page, image_ocr, mixed), `has_generated_text`, `description_status`, `vlm_model`, `prompt_version`, `image_sha256`, `crop_ref`, `bbox`, `selection_score`.

Citation label: `p. 7 > 3. Results > Figure 3` and `slide 12 > Architecture > Figure`. The answer layer's citation record for a figure carries: file, page/slide, label, caption, **crop thumbnail**, and a flag `generated=true` when the description contributed. The UI shows the actual image next to the answer - the user, not the model, is the final judge of what the picture says.

Provenance rule for answers: statements that rely only on the generated description must be phrased as interpretation ("the figure appears to show...") and tagged as AI-generated; statements with exact numbers must come from caption/OCR/table text.

Storage of crops: WebP/PNG in the existing asset store, keyed by `image_sha256`, counted against the 1 GB per-user quota; deleting a document deletes its crops, descriptions, chunks and vectors together (extends the Storage and Retention Policy).

## 7. Impact on chunking, embeddings and retrieval

**Chunking**
- New chunk kind `figure`: an isolated atom like `table` and `image_ocr`; never merged with neighbours; hard cap 480 tokens (the existing validator limit) with the description truncated first.
- The figure chunk stays in its section's parent, so parent expansion supplies surrounding prose automatically.
- Figure label also kept in the preceding paragraph's metadata via `referenced_by` (cheap two-way link).
- Chunker version bump (1.2.0, same collection while the embedding model is unchanged). E2E-08 (chunk-id stability) should land first, otherwise every enrichment renames all chunk ids of the document (today's ids embed the file hash).

**Embeddings**
- Same BGE-small text model. Risk: its semantic space was trained on text; generated descriptions are ordinary prose, so it works, but domain-specific chart language is weak. Option for later: a second vector per figure (caption-only) to keep exact-caption queries sharp.
- Re-embed only when `embedding_hash` changes (enrichment arrives, or model/prompt version changes).

**Retrieval**
- Figure chunks compete with text chunks in one ranking. Add query-intent hints in the answer layer: terms like "figure, chart, graph, plot, diagram, compare, trend, architecture" boost or filter `kind="figure"`.
- Retrieval results already carry `kind`; the context builder must render figures with the template of section 4 and attach the thumbnail.
- Calibration: figure chunks have different score distributions than prose; the score threshold work in E2E-10 must be evaluated per kind.
- Alternative considered, not recommended for MVP: page-image retrieval (ColPali-style multi-vector). It sidesteps captioning but needs a heavy model, a different index and a different citation model; revisit after the MVP benchmark.

## 8. Cost, latency and storage

All numbers below are **[assumption]** and exist to size the decision; the bake-off in section 9 replaces them.

| Item | Local 3B-7B VLM (e.g., a Qwen2.5-VL size class) | Hosted vision API |
|---|---|---|
| Hardware | needs a GPU; 7B in 16-bit wants roughly 16-24 GB VRAM, 3B or a 4-bit 7B fits smaller cards. **The current dev machine is CPU-only (embedding runs at ~5 chunks/s [measured]); a 7B VLM on CPU would take minutes per image.** | none |
| Latency per figure | about 2-10 s on a modern GPU | about 2-8 s plus network |
| Cost | GPU hours / electricity, no per-call fee | per image + output tokens; scales with user count |
| Privacy | data stays on our server | **user documents leave our system: needs consent and a privacy decision** |
| Throughput | queue with 1-2 workers | rate limits |

Per-document sizing [assumption]: a 36-page lecture PDF with 20 raster images and 3 vector diagrams -> selection keeps about 6-10 -> 1-2 minutes of background VLM time on a GPU, an upload that is searchable immediately and improves later. A 56-slide decorative template deck should keep about 0-3 figures.

Storage per described figure: crop 100-400 KB, description 1-2 KB, vector 1.5 KB. Twenty figures is about 2-8 MB of the 1 GB quota; text and vectors are negligible, crops dominate. Cache key = `image_sha256 + model + prompt_version`, so an unchanged re-upload costs nothing.

Cost controls: selection before any model call, per-document and per-user daily budgets, skip when the document is mostly text, disable per course, and surface "N figures not described" instead of failing.

## 9. Risks and failure modes

| Risk | Consequence | Mitigation |
|---|---|---|
| Hallucinated numbers / misread axes | confidently wrong answers with a citation | numbers only from caption/OCR/tables; `visible_numbers` cross-check; conflict -> drop description; answer wording rules |
| Wrong attribution (which model/series wins) | the exact failure the feature is meant to fix | require legend/entity extraction, evaluate on comparison charts specifically, show the image |
| Prompt injection through text inside an image ("ignore previous instructions") | model or later LLM steps hijacked | treat image text and descriptions as untrusted data; strict JSON schema; strip imperative text from stored descriptions; never let descriptions reach a system prompt |
| Boilerplate descriptions ("This image shows a diagram") pollute retrieval | irrelevant figure chunks rank high | minimum-information check; drop low-content descriptions; keep caption+OCR instead |
| Nondeterminism breaks re-ingestion stability | vectors churn | temperature 0, pinned model and prompt version, persisted result keyed by image hash; never regenerate silently |
| Privacy / consent | legal and trust problem for external APIs | local model or explicit opt-in; log what leaves the system |
| Cost runaway | bill / queue backlog | selection scoring, budgets, quotas, circuit breaker |
| VLM outage / timeout | blocked ingestion | two-phase design; `failed` status; retries with backoff; text-only fallback is always available |
| Missed figures (vector, grouped shapes, split) | silent gaps | detector metrics in the benchmark; report "figures detected vs described" per document |
| False keeps (decorative) | wasted cost, noise | selection precision tracked; repeated-hash rule |
| Multi-language / handwriting / low-res scans | poor output | `legibility` field; skip below threshold; no description beats a wrong one |
| Model/prompt upgrades invalidate descriptions | mixed generations in the index | provenance on every figure; background re-run; version visible in metadata |
| Licensing of the model and of copyrighted figures | compliance | review model license; store crops only for the uploading user |

## 10. Validation strategy and benchmark dataset

Existing sample data is not enough (section 1), so build a **Figure Benchmark** of about 150-200 figures:
- **Synthetic charts** (matplotlib/plotly, 60-80): bar, line, scatter, grouped bars, dual axis, with known data. Gives exact ground truth for numbers, winner, trend, and lets us vary legibility (resolution, fonts, JPEG noise).
- **Real figures** (80-100): from the team's own lecture PDFs/decks (the two Aspect-Oriented PDFs already hold 36 images), SPE_l1.pptx, `hard_PDF_1.pdf`, plus a handful of open-licensed papers with architecture diagrams, process flows and model-comparison plots. Annotated with: keep/skip label, figure type, 2-3 reference facts per figure, and 2-3 questions each.
- **Negatives** (40+): logos, icon sets, Slidesgo decorative groups, watermarks, backgrounds.

Metrics and gates (thresholds are proposals):

| Layer | Metric | MVP gate |
|---|---|---|
| Detection | recall of labelled figures, incl. vector | >= 0.85 |
| Selection | precision on keep, recall on high-value | precision >= 0.8, recall >= 0.9 |
| Description | factual accuracy on a 0-2 rubric; exact-number accuracy vs synthetic truth; hallucination rate | accuracy >= 1.5/2 mean; numeric errors < 5%; hallucinated entity < 5% |
| Retrieval | recall@5 on figure questions, with vs without description (Phase 0 vs MVP) | description must beat Phase 0 by a clear margin or it is not worth shipping |
| End-to-end | answer faithfulness and citation correctness on figure questions | no uncited figure claim; 0 numbers not found in caption/OCR |
| Operations | latency p95, cost per document, storage per document, failure rate | within the section 8 budget |

Testing approach consistent with the existing suite: the pipeline is tested with a **stub VLM** (deterministic fake adapter) so unit and integration tests stay offline; selection rules get unit tests with fixture images; the real VLM runs only in an opt-in benchmark job (like `INTELLISTUDY_MODEL_TESTS`). Add regression fixtures for every selection or description bug found. The 30-file end-to-end harness is rerun after each phase to prove no regressions in text-only documents.

Model bake-off before choosing: 2-3 candidates (a Qwen2.5-VL size, one smaller captioner, one hosted API) on the same benchmark, reporting accuracy, hallucination, latency and cost. I have not run any of these, so I make no claim about which wins.

## 11. MVP scope, production scope, and priority ordering

**Phase 0 - figure-aware text (no VLM), recommended first**
- Detect figures (raster + caption-anchored vector regions), parse captions and figure labels, link citing paragraphs, `FigureBlock` with `description_status="none"`, `figure` chunk kind, citation labels, selection layer v1 (rules only), PPTX chart values as a table.
- Success = measurable retrieval gain on the benchmark with zero model dependency. This also produces the data needed to judge what a VLM adds.

**MVP (Phase 1) - add the VLM**
- `FigureDescriber` adapter + one model, async enrichment job, cache by image hash, JSON-validated output, conflict rules, feature flag per course, per-document budget, thumbnails in citations, stub-VLM tests, benchmark v1.

**Production (Phase 2+)**
- Triage classifier, multi-panel splitting, chart-to-table extraction for quantitative charts, equation-image path (LaTeX OCR) which also addresses part of E2E-12, human correction UI, re-run on model upgrade, cost dashboards, GPU queue autoscaling, optional page-image retrieval, per-figure user overrides, multilingual.

### Priority ordering of the four candidates

Recommended order: **1) E2E-07, 2) E2E-10, 3) Multimodal (Phase 0, then MVP), 4) E2E-12**, with **E2E-08** slotted before Phase 1.

1. **E2E-07 (PPTX text-box titles) first.** Small and bounded (days, one reader). 3 of 10 decks have no headings, so every chunk from them is cited only as "slide N" and embedded without a topic. It is also a prerequisite for the new feature: a figure's citation and context are built from the slide title. High value per effort.
2. **E2E-10 (thresholds / reranking / bibliography) second, and before the RAG Answer Layer.** The answer layer's refusal logic cannot be correct without it: unrelated questions currently score 0.49-0.68, indistinguishable from weak true matches, and reference lists can outrank an abstract. Every future feature, including figure chunks (new score distribution), depends on this calibration. It needs the labelled evaluation set that the multimodal benchmark would also reuse.
3. **Multimodal third.** It is the largest item (new schema, detector, selector, async job, model decision) and the one with the most unresolved decisions (GPU, privacy, budget). Its value is real for lecture material (the lecture PDFs carry 36 images) but unproven on our current data, which is why Phase 0 comes first and the VLM waits for the benchmark. It should not block the RAG Answer Layer MVP, which can ship text-and-tables first and add figures behind the chunk-kind boundary.
4. **E2E-12 (equation fragments) last.** It affects math-heavy PDFs only, does not corrupt content (fragments are real text, only badly segmented), and has no downstream blocker. A proper solution (equation regions as LaTeX) overlaps with the Phase 2 equation-image path, so work done earlier would likely be redone. Revisit when math coursework is a stated target.

Dependency note: E2E-08 (stable chunk ids) should precede Phase 1, because enrichment rewrites figure chunks and, under today's file-hash ids, a re-upload renames every chunk of the document.

---

## 12. Decisions needed from the team

1. **Where does the VLM run?** Local GPU (is one available?), a hosted API, or both behind the adapter.
2. **May user documents be sent to an external API?** If yes, with what consent and retention terms.
3. **Budget:** acceptable cost and latency per document, and whether figure enrichment is on by default or opt-in per course.
4. **Scope of "figure":** are scientific plots and architecture diagrams the target, or also slide photos and screenshots? This changes selection rules and the benchmark.
5. **Who annotates the benchmark** (about 150-200 figures, roughly 2-3 person-days [assumption]).
6. **Acceptance:** are the proposed gates in section 10 acceptable, particularly "Phase 0 first; the VLM must beat it".

## 13. Not decided or verified here

No model was run, so every latency, cost, VRAM and accuracy statement is an assumption. The statement that captions plus citing text capture most of the value is a hypothesis to be tested by Phase 0, not a finding. Vector-figure detection reliability on real papers is untested. Nothing in this document has been implemented.

---

## 14. Corpus coverage assessment (2026-11-15)

Scope: the 30-file **evaluation corpus** (`evaluation.index_builder.corpus_files()`, the files that the retrieval set and the 111 answer cases run on), plus the 5 synthetic DOCX files that appear only in the e2e set (padding, random or repeated text, no visual content). Method: every file was run through the current ingestion and chunking pipeline (approximate token counter); visual elements were counted in the raw files (PDF images and drawings, PPTX/DOCX XML); the contact sheets of every hand-labelled figure candidate were inspected. Nothing was changed.

### 14.1 Measured
**Corpus composition** (share of the 172,662 indexed tokens):

| Group | Files | Tokens | Visual content |
|---|---|---|---|
| arXiv math papers (hard_PDF_1-10) | 10 | 59% | 5 figures in total (hard_PDF_1: 3 plots + 1 diagram; hard_PDF_8: 1); 1,228 formula-like text blocks (about 22.8k characters) |
| DOCX samples | 5 | 16% | 29 pictures, 2 kept as figures; no charts, no equations |
| Lecture material (AOP 1-2, Sections 01-03, SPE_l1) | 6 | 12% | 47 kept figures (box-and-arrow diagrams, code screenshots, one histogram, matrix/formula images, one line chart); **104 Equation Editor (`Equation.3`) OLE objects on 21 slides of SPE_l1** |
| Proposal, test.pdf, test2.pdf | 3 | 6% | 9 vector architecture diagrams, 1 caption-only figure, 1 scanned page |
| Slide templates (Slidesgo, SlideEgg, poster, admission) | 6 | 6% | Decoration (2,700+ grouped / textless shapes); 8 kept figures |

The corpus contains **no SmartArt and no native PowerPoint charts**.

**Channels that reach retrieval** (share of indexed tokens): native text (paragraphs, lists, headings) 92.1% (of which about 3.5 percentage points are formula text that arrives as fragmented, linearised strings, see E2E-12); tables 4.9%; figure chunks 2.7%; image OCR outside figures 0.1%; whole-page OCR under 1%.

**Figure text sources** (74 kept figures): OCR text 47; vector inner text 21; caption 4; citing sentences 3 (all in hard_PDF_1); no text at all 4 (recorded, not indexed). Captions and citing sentences, the anchors Phase 0 was designed around, are nearly absent outside the one real paper: lecture slides carry no captions.

**Content that does not reach the index at all:** the 104 SPE_l1 equations (their WMF previews are skipped as undecodable; the OLE equation data is not read), 4 text-less figures, and the visual structure (arrows, curves, bar heights) of every figure. Of these, **Equation Editor / OLE equations are the largest category**.

**QA benchmark exposure:** 2 of the 72 answerable cases (x24, x25) are figure questions. The three failures that touch the AOP1 assessment-criteria page (a04, x01, x18) concern flattened native text (a timeline graphic read as one paragraph and two course codes interleaved), not an image.

### 14.2 Phase 0 sufficiency per file (measured counts + inspection)
- **Insufficient:** `Section 02 - Classical Encryption Techniques I.pptx` (letter-frequency histogram, Playfair grids as images, Hill cipher formula and worked-matrix images, OCR garbled); `SPE_l1.pptx` (104 equations lost, not a vision problem; one line chart).
- **Partial:** `hard_PDF_1.pdf` (the only real scientific-figure file: 3 plots + 1 diagram, captions and citing sentences reach the index, curve content does not); `Statistical Methods in Public Health ... Slidesgo.pptx` (2 real figures with no text, not indexed).
- **Sufficient or unaffected:** the other 26 files. The AOP lectures and the proposal have diagrams whose labels reach the index and whose meaning largely repeats the adjacent text; hard_PDF_2-10 have no figures (their gap is formulas, not Phase 0); the template decks are decorative.

### 14.3 Estimates and assumptions (not measured)
How much meaning a visual adds beyond its surrounding text is a judgement from the contact sheets, so the figures below are ranges, not measurements:

| Scope | Reachable as usable text | Superficially reachable or inaccessible |
|---|---|---|
| Whole evaluation corpus (dominated by papers) | about 90-94% | about 6-10% (formulas first, then plot data, diagram relations, text-less figures) |
| Lecture material only | about 75-85% | about 15-25% (SPE equations the largest single loss; Section 02 images; diagram relations mostly duplicated by bullets) |

Roughly a third to a half of the inaccessible content needs a vision model; the rest is formula / equation extraction.

Expected Vision gain (estimate, no model run): retrieval on the current benchmark about 0 (hit@5 is already 0.96 and no retrieval failure involves an image); QA 0 to +2 cases (x24, x25), within the benchmark's noise of about +/-0.10. On the corpus itself, descriptions would add meaning for about 10-12 figures that matter (Section 02, hard_PDF_1 plots, the SPE chart, two Statistical Methods figures); they would not recover the SPE equations unless the WMF previews are rendered first (not possible on this machine). Differences between GPT-4o Vision, Gemini Vision and Qwen-VL cannot be measured on the current benchmarks; the hosted models need the same data-sharing decision as the text evaluation, and Qwen-VL needs a GPU this machine does not have.

### 14.4 Conclusion and recommended order
**Vision is not currently the highest-priority content gap.** The largest inaccessible category is equations, which needs extraction rather than a vision model, and the current QA benchmark cannot show a Vision gain. Order:
1. **Stronger-model text evaluation** (prepared; `real_model_eval_report.md` section 9). It decides the grounding policy, which figure answers also depend on.
2. **Equation extraction without vision**: read Equation Editor / OMML objects as text, and merge the fragmented formula lines of PDFs (E2E-12).
3. **Figure-question benchmark** on the content that needs it (Section 02, the SPE chart, hard_PDF_1, a few AOP diagrams; about 30-40 questions), with the Phase 0 baseline scored first. This annotation work can start in parallel with step 1.
4. **Vision bake-off** (the gate of section 10 and `phase0_report.md` section 5), only on that benchmark.

### 14.5 Open findings from this assessment (not fixed)
- **F-COV-1, wrong `source_kind` on DOCX/PPTX chunks:** chunks are tagged `ocr_page` whenever any image on the page or slide was OCR'd, even when OCR produced no text (all 8,089 native tokens of `sample-long.docx` are tagged as OCR). This misleads any OCR notice in the UI and any coverage statistic based on `source_kind`.
- **F-COV-2, Equation Editor objects dropped:** the 104 `Equation.3` OLE objects in `SPE_l1.pptx` reach no block; only a mild-skip warning for their WMF previews is recorded. *Correction 2026-11-23 (measured):* 104 counts every object twice (each graphic frame holds the same `p:oleObj` in `mc:Choice` and `mc:Fallback`); there are **52 unique equations** (52 distinct `ppt/embeddings/*.bin` parts) on 21 slides, plus 2 `MS_ClipArt_Gallery` objects. Every equation part is an OLE2 file with an `Equation Native` stream holding MTEF v3 data (Equation Editor 3.0, Windows); a throwaway decoder read all 52 without error, so the text is recoverable without a vision model (see project_context section 8, item 16).
- **F-COV-3, flattened layout on AOP1 p. 5 (Assessment Criteria):** a timeline graphic becomes one run-on paragraph, and the CSE 447 / CSE 434 weights are interleaved in list items. This is the likely root of the a04, x01 and x18 answer failures. *Re-diagnosed 2026-11-23 (measured):* the flattening does not cause the a04/x01 misses; the chunk lacks document context (see `real_model_eval_report.md` section 13).
- **F-COV-4, unselected labelled keepers:** Section 03's one hand-labelled keeper is not selected, and the 2 Statistical Methods figures are kept but carry no text, so they are not indexed (known Phase 0 limits).

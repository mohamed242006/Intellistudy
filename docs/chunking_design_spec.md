# IntelliStudy Chunking Design Specification (v1.0)

> **STATUS: HISTORICAL (superseded in part, banner added 2026-11-15).** Kept for design context: it records the
> original chunking rules and the reasoning behind them. The text below is unchanged, including its own §12-13 notes.
> The current single source of truth is [`project_context.md`](project_context.md). Outdated here:
> - **Chunk ID format** (§3, `{doc_id}-{ordinal:05d}-{content_hash[:8]}`): replaced in chunker 1.3.0 by
>   `c-{hash12}` / `p-{hash12}` - project_context.md §3.2 and §5.
> - **Chunker version** (`chunker_version "1.0.0"`): current is **1.3.0** - project_context.md §3.2.
> - **Schema version** (`"2.0"`): current is **2.1** - project_context.md §3.1.
> - **Figure chunks**: not in the `kind` list here; `figure` exists since chunker 1.2.0 - project_context.md §3.8.
> - **Thresholds in the §1.1 table** (`slide_min_body_tokens` 20, `ocr_min_confidence` 0.55, `include_hidden`):
>   superseded by §12-13 of this file and project_context.md §3.2 (6 tokens; OCR < 0.3 dropped, < 0.6 flagged;
>   hidden slides always excluded).
> - **Citation markers** `[C1]..[Ck]` (§8.5): the answer layer uses `[S1]..[Sn]` in prompts and `[n]` for readers -
>   project_context.md §3.10.
> - **Embedding and vector store** (§12 "Not yet built: vector-store adapter ... embedding job"): built -
>   project_context.md §3.3-3.4. **PostgreSQL persistence and the transactional re-ingestion with tombstoned rows (§9,
>   §10.1)** are still NOT built: stale chunks are deleted immediately - project_context.md §3.6 and §7.
> - **Reranker, answer layer, real-model evaluation**: not covered here - project_context.md §3.5, §3.10, §11.

Status: implementation-ready. Input: `Document` schema 2.0 from `ai/ingestion`. Output: `Chunk` records ready for PostgreSQL + ChromaDB.
Proposed package: `ai/chunking/` (`models.py`, `chunker.py`, `tokens.py`, `ids.py`, `render.py`, `config.py`).

Terminology: "block" = `Block` (`ai/ingestion/models.py`); "unit" = `Document.unit` (`page` | `slide` | `document`).

---

## 0. Inputs and what the schema does and does not give us

| Needed by chunker | Where it comes from | Caveat (verified in code) |
|---|---|---|
| Ordered content | `Document.blocks` (`Block.order`, global) | Complete for PDF, DOCX, PPTX |
| Section path | `Block.heading_path` (tuple, own title included for headings) | PDF/DOCX carry across pages; PPTX resets per slide |
| Location | `Block.page_number`, `Document.unit`, `Block.bbox` (PDF only) | DOCX is always page 1 -> cite by heading path |
| Table rows/header | `PageContent.tables[block.ref_index].rows` | `Block.text` of a table is **pipe text for PDF, key/value text for DOCX/PPTX** -> chunker re-renders from `rows` |
| OCR provenance | `BlockType.IMAGE_OCR` (+ `Block.confidence` 0-1), `PageContent.ocr_applied` | Whole-page OCR text arrives as normal paragraph blocks: derive "from OCR" from `page.ocr_applied` |
| Hidden slides | `Document.metadata["slides"][i]["hidden"]` (`slide_number`) | Not on the block |
| Speaker notes | `BlockType.NOTES` | One block per slide, last on the slide |
| Extraction quality | `PageContent.confidence`, `Document.statistics["low_confidence_pages"]` | Confidence is per page/slide |
| Identity | `Document.source` (`doc_id`, `sha256`, `file_name`, `file_type`, `unit`, `title`, `language`) | `doc_id = sha256[:16]` is a **content** id |
| Ownership | **not in the document** | Supplied by the caller in `ChunkContext` (user_id, course_id, document_uid) |

```python
@dataclass(frozen=True)
class ChunkContext:
    user_id: str
    course_id: str
    document_uid: str            # stable DB identity of the uploaded document (survives re-upload)
    include_hidden: bool = False
    embedding_model: str = ""    # recorded in metadata, used for tokenizer selection
```

Public API:

```python
class Chunker:
    def __init__(self, config: ChunkConfig, tokenizer: TokenCounter): ...
    def chunk(self, document: Document, ctx: ChunkContext) -> list[Chunk]: ...
```

Pure function of its inputs (no I/O, no randomness): same input -> byte-identical output (NFR-ING-01).

---

## 1. Chunking algorithm

### 1.1 Configuration (defaults)

| Parameter | Default | Meaning |
|---|---|---|
| `target_tokens` | 400 | Soft target per chunk |
| `max_tokens` | 480 | Hard cap of `embedding_text` (must be <= embedding model limit minus margin) |
| `min_tokens` | 80 | Smaller chunks are merged where allowed (section merge, 1.4) |
| `overlap_tokens` | 60 | Overlap between consecutive text chunks (section 4) |
| `slide_min_body_tokens` | 20 | Slides with less body content produce no chunk (section 6) |
| `table_max_tokens` | 400 | Tables above this are split by rows (section 5) |
| `ocr_min_confidence` | 0.55 | Image OCR below this is dropped (matches `OCRProcessor`) |
| `low_confidence_page` | 0.6 | Same threshold as `low_confidence_pages` |
| `drop_below_page_confidence` | 0.3 | Pages below are not indexed (warning recorded) |

Token counting: `TokenCounter` wraps the embedding model's own tokenizer (`count(text) -> int`). Fallback when no tokenizer is available: `ceil(len(text) / 4)`. The counter name is stored in each chunk (`tokenizer`), so mixed counts are detectable.

### 1.2 Pipeline

```
Document
 1. select       drop hidden slides, empty blocks, drop-level pages, low-confidence image OCR
 2. sectionise   group consecutive blocks into sections (leaf heading_path; slide = section)
 3. atomise      blocks -> atoms (unsplittable-by-default units)
 4. pack         greedy fill of atoms up to target_tokens inside a section
 5. split        oversize atoms split at natural boundaries (table rows, list items, sentences)
 6. merge        small chunks merged forward within the same parent section
 7. overlap      attach overlap_prefix (text chunks only, same section)
 8. finalise     ids, metadata, citations, invariants check
```

### 1.3 Step details

**1. select**
- Exclude blocks on pages whose `PageContent.confidence < drop_below_page_confidence` (record `ChunkReport.skipped_pages`).
- Exclude blocks of slides with `hidden=True` unless `ctx.include_hidden`.
- Drop `IMAGE_OCR` blocks with `confidence < ocr_min_confidence`; drop blocks whose text is empty after strip.
- Never drop headings: they feed `heading_path` and context prefixes even when a section ends up empty.

**2. sectionise**
A *section* is a maximal run of consecutive selected blocks sharing the same `heading_path`.
- A heading block starts a new section (its own path).
- PPTX: additionally, a section boundary at every slide change; the slide title heading is the section head.
- DOCX and PDF: sections may span pages (PDF) - `page_start/page_end` record that.
- The section's `parent` is `heading_path[:-1]`.

**3. atomise** (atoms are the smallest things the packer moves around)

| Block(s) | Atom |
|---|---|
| `HEADING` | Never a standalone atom: attached as the *lead* of the next atom(s) of its section; contributes to `heading_path` and the context prefix |
| `PARAGRAPH` | One atom (splittable at sentence boundaries if > `max_tokens`) |
| consecutive `LIST_ITEM` | One *list atom* (a list is kept together; splittable only between items) |
| `TABLE` | One *table atom* (rules in section 5) |
| `CHART` | One atom, never split (always short) |
| `IMAGE_OCR` | One atom, labelled (section 7) |
| `NOTES` | One atom, **always its own chunk** (sections 6, 7 of this document) |

**4. pack**
```
chunk = []
for atom in section.atoms:
    if atom.kind == NOTES or atom.kind == TABLE:  flush(); emit_special(atom); continue
    if tokens(chunk) + tokens(atom) <= target_tokens:   chunk.append(atom)
    elif tokens(chunk) >= min_tokens:                    flush(); chunk=[atom]
    else:                                                chunk.append(atom)   # allow overshoot up to max_tokens
    if tokens(chunk) > max_tokens: split_oversize(chunk)  # step 5
flush()
```
Rules: a heading is never the last element of a chunk (it moves to the next chunk); a list is not separated from the paragraph that introduces it when that paragraph ends with `:` (they form one atom).

**5. split oversize**
- Paragraph: split at sentence boundaries (`.`, `?`, `!`, `;`, Arabic `؟`), then at whitespace as the last resort. Never split inside a code span, number, or `[...]` marker.
- List atom: split between items, never inside an item; `list_marker` numbering is preserved (item "3." stays "3.").
- Table: section 5.

**6. merge**
A chunk with `< min_tokens` is merged **forward** into the next chunk when both are in the same parent section and the merged size `<= max_tokens`; otherwise merged backward; otherwise kept (short chunks are legitimate, e.g. a definition). Merging never crosses a slide, a table, a notes chunk or a page-confidence drop. After merging, `heading_path` is the longest common prefix of the merged sections (so citations stay valid at the coarser level) and `section_titles` lists the merged titles.

**7. overlap** - section 4. **8. finalise** - sections 2, 3, 8, 10.

### 1.4 Invariants (must be asserted in tests and at the end of `chunk()`)

1. Every selected non-heading block's text appears in exactly one chunk's own `text` (no loss, no duplication in `text`).
2. `block_orders` of a chunk are strictly increasing; ranges of different chunks do not interleave except via `overlap_prefix`.
3. No chunk spans two documents, two slides, or a hidden/visible boundary.
4. `token_count(embedding_text) <= max_tokens` except for a documented single-atom overflow (`oversize=True`).
5. Determinism: running twice yields identical `chunk_id`s and text.
6. `heading_path` of a chunk is a prefix-compatible ancestor of every contained block's `heading_path`.

---

## 2. Chunk metadata schema

```python
@dataclass(frozen=True)
class Chunk:
    # identity
    chunk_id: str                 # section 3
    ordinal: int                  # 0-based position within the document's chunk list
    kind: str                     # "text" | "table" | "chart" | "notes" | "image_ocr" | "mixed"

    # content
    text: str                     # own content, no overlap; shown to users and given to the LLM
    embedding_text: str           # context prefix + overlap_prefix + text (what gets embedded)
    overlap_prefix: str           # <= overlap_tokens, may be ""
    token_count: int              # tokens of embedding_text
    content_hash: str             # sha1 of normalised `text` (16 hex)

    # provenance (document level)
    doc_id: str                   # SourceInfo.doc_id (content id)
    document_uid: str             # ChunkContext.document_uid (stable DB id)
    sha256: str
    file_name: str
    file_type: str                # pdf | docx | pptx
    unit: str                     # page | slide | document
    title: str | None             # SourceInfo.title

    # ownership (enforced server-side on retrieval, FR-RAG-03)
    user_id: str
    course_id: str

    # location / citation
    page_start: int               # page or slide; 1 for docx
    page_end: int
    slide_number: int | None      # = page_start for pptx, else None
    heading_path: tuple[str, ...]
    section_titles: tuple[str, ...]   # only when sections were merged
    block_start: int              # first Block.order
    block_end: int                # last Block.order (inclusive)
    block_orders: tuple[int, ...]
    citation_label: str           # structure.citation_label(first_block, unit) + range, e.g. "p. 4-5 > Caching > LRU"
    bboxes: tuple[tuple[int, tuple[float, float, float, float]], ...]  # (page, bbox), PDF only, capped (<= 16)

    # quality
    confidence: float             # min(page confidences, block confidences)
    low_confidence: bool          # confidence < low_confidence_page
    source_kind: str              # "native" | "ocr_page" | "image_ocr" | "mixed"
    has_table: bool
    hidden: bool                  # True only if ctx.include_hidden and the slide is hidden

    # table-specific
    table_index: int | None
    table_part: int | None        # 1-based
    table_parts: int | None

    # versioning
    chunker_version: str          # "1.0.0"
    schema_version: str           # Document.schema_version ("2.0")
    embedding_model: str
    tokenizer: str
    language: str | None          # SourceInfo.language (may be None until detection exists)
    ingested_at: str              # SourceInfo.ingested_at
```

`ChunkReport` (returned alongside, logged and stored on the document row): `chunk_count`, `skipped_pages`, `dropped_blocks`, `oversize_chunks`, `merged_chunks`, `warnings`.

---

## 3. Chunk ID generation

```
chunk_id = f"{doc_id}-{ordinal:05d}-{content_hash[:8]}"
```
- `doc_id` ties the chunk to file *content* (`sha256[:16]`).
- `ordinal` keeps ids human-sortable and unique within a document.
- `content_hash[:8]` (sha1 of whitespace-normalised `text`) changes when the chunk's content changes, which is what allows embedding reuse and stale detection (section 9).

Collision handling: ids are unique within `(doc_id)` by construction (ordinal). Two different uploads of identical bytes share `doc_id`; they are told apart by `document_uid` in metadata and in the vector-store key (section 10: the Chroma id is `f"{document_uid}:{chunk_id}"`).

`content_hash` normalisation: NFC, collapse whitespace, strip. It excludes `overlap_prefix` and heading context, so changing overlap settings does not alter ids.

---

## 4. Overlap strategy

- Purpose: keep sentences that straddle a boundary retrievable. It is **not** applied everywhere.
- Applies only between *consecutive text/list chunks of the same section* (same `heading_path`, same slide).
- Never across: a section boundary, a slide boundary, a table chunk, a notes chunk, an OCR-only chunk, or a document boundary.
- Size: the last whole sentences of the previous chunk's `text` whose total is `<= overlap_tokens` (at least one sentence if it fits, otherwise none). Never cut mid-sentence.
- Storage: `overlap_prefix` is separate. `text` stays overlap-free so citations, de-duplication and LLM context assembly never repeat sentences. `embedding_text` is the only place the overlap appears.
- Retrieval consequence: when two adjacent chunks are both retrieved, the answer builder concatenates `text` (not `embedding_text`) in `block_start` order.

---

## 5. Table chunking rules

Rendering (from `PageContent.tables[ref_index].rows`, not from `Block.text`):

| Field | Format |
|---|---|
| `text` (display/LLM) | Markdown pipe table: header row, separator, rows; cells whitespace-collapsed |
| `embedding_text` body | Key/value per data row: `Header: value` lines, rows separated by a blank line (`TableData.to_key_value_text()` semantics) |

Rules:
1. **Atomic if it fits**: `tokens(table_text) <= table_max_tokens` -> exactly one chunk, `kind="table"`, never merged with neighbours, never overlapped.
2. **Otherwise split by rows**: consecutive data rows are grouped until the group (plus the repeated header) reaches `target_tokens`. A row is never split between chunks.
3. **Header repeated** in every part; `table_part = i`, `table_parts = n`. Header-less tables (single row, or first row empty) use positional `Column k` labels and are treated as one logical header.
4. **Single oversize row** (> `max_tokens`): split by cell groups, first column (row label) repeated in each part.
5. **Context prefix**: the immediately preceding paragraph block, if `<= 60 tokens` and in the same section, is copied into `embedding_text` as `Context: ...` (and not removed from its own chunk). This keeps "Table 2 compares ..." attached to the data it explains.
6. `heading_path`, `page_start/page_end`, `bboxes` come from the table block; `table_index = block.ref_index`.
7. Pipe-vs-key/value inconsistency in the current readers is resolved here and nowhere else (single source of truth: `render.py`).

---

## 6. Slide chunking rules (PPTX; unit = `slide`)

1. **A chunk never crosses a slide.** Slide = section root; `heading_path` resets per slide, so chunks carry `(slide_title,)`.
2. **Default: one chunk per slide** containing, in block order: title (as context), body paragraphs/list items, chart text, OCR text, tables when small. If it exceeds `target_tokens`, apply pack/split inside the slide and repeat the slide title in every `embedding_text` prefix.
3. **Title-only / divider slides** (`body tokens < slide_min_body_tokens`, no table, no OCR): no chunk is produced. Their title survives in the document outline and in `deck_context` of neighbouring chunks.
4. **Speaker notes -> separate chunk** (`kind="notes"`), same `slide_number`, `source_kind="native"`, metadata `is_notes=True` (stored as `kind`). Reason: notes are explanatory prose, differ in register from bullets, and citations should say "speaker notes".
5. **Hidden slides** are excluded unless `include_hidden`; when included, `hidden=True` on the chunk.
6. **Tables on slides** follow section 5; a small table stays in the slide chunk only if the whole slide fits in `target_tokens`, otherwise it becomes its own chunk.
7. **Context prefix for slides**: `"{deck_title} | Slide {n}: {slide_title}"`.
8. `page_start == page_end == slide_number`.

DOCX (`unit="document"`): no page numbers; `page_start=page_end=1`; the section/heading path is the location. PDF: `page_start/page_end` from first/last block; a chunk may span two pages inside one section, a page break is not a boundary.

---

## 7. OCR text handling

| Source | How it appears | Chunking behaviour |
|---|---|---|
| Native text layer | normal blocks | default |
| Whole-page OCR (scanned PDF page) | normal paragraph blocks, `page.ocr_applied=True` | `source_kind="ocr_page"`; chunk `confidence = page.confidence` |
| Image OCR | `BlockType.IMAGE_OCR`, `Block.confidence` | labelled atom |

Rules:
1. Image OCR is rendered with the label `[Image text]` in `text` so the LLM and the user can see where it came from; `embedding_text` also contains it (OCR noise is thereby recognisable).
2. Image OCR is **not merged with native text** in PDF/DOCX chunks (different reliability). On slides it may share the slide chunk (rule 6.2); then `source_kind="mixed"`.
3. `confidence` of a chunk = min over its blocks' confidences and page confidences; `low_confidence = confidence < 0.6`.
4. `low_confidence` chunks are indexed (so students can still search them) but carry the flag so retrieval can down-weight or the answer can be marked low confidence (FR-CIT-04, NFR-AIQ).
5. Pages below `drop_below_page_confidence` are not indexed and are listed in `ChunkReport`.
6. Repeated image OCR (logos) has already been removed by ingestion (`ocr_skipped_reason="repeated"`); the chunker does not re-detect it.
7. `has_ocr` is derivable: `source_kind != "native"`.

---

## 8. Citation preservation strategy

Goal: every statement in an answer can be traced to a location the student can open.

1. **Location triple on every chunk**: `(page_start, page_end)` or `slide_number`, `heading_path`, `block_start..block_end` + `block_orders`.
2. **`citation_label`** is precomputed with `structure.citation_label(first_block, unit)`; for ranges the page part becomes `p. 4-5`. Labels:
   - PDF: `p. 4 > Caching > LRU`
   - PPTX: `slide 7 > Cache replacement`
   - DOCX: `Caching > LRU` (no page)
3. **Highlighting (FR-CIT-03)**: `bboxes` (PDF only, up to 16 `(page, bbox)` entries from `Block.bbox`); for DOCX/PPTX highlight falls back to the heading/slide.
4. **Chunk text is derivable from blocks**: `block_orders` lets the UI re-open the exact block range from stored `Document`/blocks, so citations never depend on string search.
5. **Marker contract with the LLM**: the prompt builder numbers retrieved chunks `[C1]..[Ck]` and keeps the map `C# -> chunk_id`; answers may only cite supplied markers (FR-CIT-04). Stored citation rows reference `chunk_id` + `document_uid`.
6. **Stability**: citations survive re-ingestion of an unchanged file (same ids). For a changed file, old citations stay readable because old chunks are kept as tombstoned rows for `retention_days` (section 9).
7. **Merged sections** keep correctness by using the common-prefix `heading_path` and listing `section_titles`.

---

## 9. Re-ingestion strategy

Identities: `document_uid` (stable DB id of the upload slot), `doc_id` (content hash), `chunker_version`, `embedding_model`.

| Situation | Detection | Action |
|---|---|---|
| Same bytes, same chunker/embedding version | `sha256` equal and `chunker_version` equal | **No-op**; return existing chunks |
| Same bytes, new `chunker_version` | version differs | Re-chunk; reuse embeddings for chunks whose `content_hash` and `embedding_model` are unchanged; replace the rest |
| Changed file (new bytes) for same `document_uid` | `sha256` differs | Chunk new document; diff by `content_hash`; **upsert** new/changed, **delete** vanished; reuse embeddings of unchanged `content_hash` |
| Embedding model changed | `embedding_model` differs | New collection (section 10); re-embed all; old collection dropped after verification |
| Duplicate upload in the same course (FR-UPL-04) | same `sha256` + `course_id` | Offer to reuse; no new chunks |
| Failed / interrupted run | job status | Idempotent: chunk ids are deterministic, so a retry upserts the same rows |

Procedure (transactional):
1. Compute new chunks (pure).
2. In PostgreSQL, within one transaction: insert new chunk rows with `status="pending"`; mark old rows `status="superseded"`.
3. Embed only chunks with no reusable embedding (cache key: `embedding_model + content_hash`).
4. Upsert vectors into Chroma.
5. In PostgreSQL: set new rows `status="active"`, old rows `"deleted"` (physical delete after `retention_days`, default 7).
6. Delete superseded vectors from Chroma by id.
A document becomes retrievable only after step 5 (NFR-REL-02). The Chroma index must be rebuildable from PostgreSQL alone (NFR-REL-07), so `embedding_text` and metadata are stored in `document_chunks`.

---

## 10. Vector-database-ready output schema

### 10.1 PostgreSQL `document_chunks` (source of truth, ADR-009)

| Column | Type | Notes |
|---|---|---|
| `chunk_id` | text | per section 3 |
| `document_uid` | uuid FK | with `chunk_id` forms the key |
| `ordinal` | int | |
| `kind`, `source_kind` | text | |
| `text` | text | |
| `embedding_text` | text | |
| `token_count` | int | |
| `content_hash` | char(16) | |
| `heading_path` | jsonb | array of strings |
| `page_start`, `page_end`, `slide_number` | int | |
| `block_start`, `block_end` | int | |
| `block_orders` | jsonb | |
| `bboxes` | jsonb | |
| `citation_label` | text | |
| `confidence` | real | |
| `low_confidence`, `hidden` | bool | |
| `table_index`, `table_part`, `table_parts` | int | |
| `chunker_version`, `embedding_model`, `tokenizer` | text | |
| `status` | text | pending / active / superseded / deleted |
| `created_at` | timestamptz | |

### 10.2 ChromaDB record

Collection name: `chunks__{embedding_model_slug}__c{chunker_major}` (e.g. `chunks__bge-m3__c1`). Vector dimension is implied by the model; changing model or chunker major starts a new collection.

```python
{
  "id": f"{document_uid}:{chunk_id}",
  "document": text,                       # shown / used as LLM context
  "embedding": [...],                     # embedding of embedding_text
  "metadata": {                           # Chroma allows only str | int | float | bool
      "user_id": str, "course_id": str, "document_uid": str, "doc_id": str,
      "file_name": str, "file_type": "pdf|docx|pptx", "unit": "page|slide|document",
      "page_start": int, "page_end": int, "slide_number": int,   # -1 when not applicable
      "heading_path": "A > B > C",         # joined string (display)
      "heading_path_json": '["A","B","C"]',
      "heading_top": "A",                  # first element, for cheap filtering
      "kind": "text|table|chart|notes|image_ocr|mixed",
      "source_kind": "native|ocr_page|image_ocr|mixed",
      "confidence": float, "low_confidence": bool, "hidden": bool,
      "block_start": int, "block_end": int,
      "token_count": int, "ordinal": int,
      "citation_label": str, "content_hash": str,
      "table_index": int, "table_part": int,                      # -1 when not applicable
      "chunker_version": str, "embedding_model": str,
  },
}
```

Notes:
- **No lists or None** in Chroma metadata: lists are JSON strings, None becomes `-1` or `""`.
- **`bboxes` and `block_orders` stay in PostgreSQL** (size); retrieval joins by `chunk_id`.
- **Server-side scoping** (FR-RAG-03): every query must include `where={"$and":[{"user_id":u},{"course_id":c}]}`; the vector-store adapter refuses calls without both keys.
- **Filters supported** (FR-RAG-05): `document_uid`, `heading_top`, `page_start`/`page_end` ranges, `kind`, `low_confidence`, `hidden=False`.
- **Delete by document**: `where={"document_uid": uid}`.

### 10.3 Adapter boundary (NFR-SCA-04)

```python
class VectorStore(Protocol):
    def upsert(self, collection: str, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]) -> None: ...
    def delete(self, collection: str, *, document_uid: str, keep_ids: set[str] | None = None) -> int: ...
    def query(self, collection: str, vector: Sequence[float], *, user_id: str, course_id: str,
              k: int, filters: dict | None = None) -> list[ScoredChunk]: ...
```

---

## 11. Acceptance tests (write these first)

1. Invariants 1-6 on one sample each of PDF, DOCX, PPTX (use `data/uploads`).
2. No chunk crosses a slide; hidden slides absent by default, present with `include_hidden`.
3. Table > `table_max_tokens` splits by rows, header repeated, no row split; small table is one chunk.
4. Notes are separate chunks with the correct `slide_number`.
5. Overlap present only between consecutive text chunks in one section; absent across tables, slides, sections.
6. Same input twice -> identical ids; edited paragraph changes only that chunk's `content_hash`/id suffix.
7. Re-ingest unchanged file -> zero new embeddings; edited file -> only changed chunks re-embedded.
8. Chroma metadata contains only scalar types; query without `user_id`/`course_id` is rejected.
9. `citation_label` for each file type matches the formats in section 8.
10. Low-confidence page chunk flagged; page below 0.3 not indexed and reported.

## 12. Decisions (confirmed) and implementation status

| Decision | Value | Consequence |
|---|---|---|
| Embedding model | `BAAI/bge-small-en-v1.5` | English only, 384-d, 512-token window; `max_tokens=480`; collection `chunks__bge-small-en-v1.5__c1`; documents embedded **without** instruction, queries with `QUERY_INSTRUCTION`; normalise embeddings, cosine space |
| Title-only slides | Not indexed | Implemented: a slide with no body (or fewer than `slide_min_body_tokens=6` body tokens and no table/chart/image text) yields no chunk; listed in `ChunkReport.skipped_slides`; speaker notes of such a slide are still indexed |
| Tombstone retention | 7 days | `TOMBSTONE_RETENTION_DAYS` in `ai/chunking/config.py`; used by the re-ingestion job (not yet built) |
| Language | English only | Arabic documents are out of scope until the model and OCR language change (FR-ING-16) |

Implementation notes (deviations from the first draft of this spec, found while implementing):

1. **Merge rule**: top-level sibling sections are never merged (it would leave an empty `heading_path`); only siblings sharing a non-empty parent, or a section followed by its own sub-section, are merged.
2. **Page-drop rule**: pages are dropped for low confidence only for whole-page OCR pages of PDFs (`unit == "page"` and `page.ocr_applied`). For DOCX/PPTX the page confidence describes images only, so it must not flag or drop text.
3. **Chunk confidence**: PDF native chunks use the page confidence; DOCX/PPTX native text is 1.0; image-OCR blocks use their own confidence; the chunk takes the minimum.
4. **Title-only threshold** is 6 tokens (a 20-token threshold dropped real two-bullet slides).
5. Ordinals are assigned after merging; a section's heading chunk text excludes headings (they live in `heading_path` / `embedding_text` prefix).

Status: `ai/chunking/` implemented (`config`, `tokens`, `ids`, `render`, `models`, `chunker`); `tests/test_chunker.py` (30 tests) passes. Not yet built: vector-store adapter, PostgreSQL persistence, embedding job, re-ingestion job (section 9), per-job pipeline isolation.

## 13. Superseded by the final decisions (see `chunking_architecture.md`)

* Hidden slides are **always** excluded (the earlier `include_hidden` option was removed).
* Charts are isolated chunks (never merged, never overlapped), like tables and notes.
* OCR below 0.3 is not indexed and OCR below 0.6 is flagged (both whole-page and image OCR).
* Hierarchical output: children (embedded) and parents (section context, never embedded).
* The implementation is split into `BlockSelector`, `AtomBuilder`, `ChunkBuilder`, `ParentBuilder`, `ChunkValidator` composed by `ChunkingEngine`; the single `Chunker` class described earlier no longer exists.

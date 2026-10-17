"""ChunkBuilder: sections -> atoms -> packed drafts -> merged -> child chunks.

Packing never crosses a section or a slide; overlap is attached only between
consecutive plain-text chunks of one section; tables, charts and notes always
form chunks of their own (docs/chunking_design_spec.md, sections 1, 4-6).
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.chunking.atoms import ISOLATED_KINDS, Atom, AtomBuilder
from ai.chunking.citation import block_ranges, citation_label
from ai.chunking.config import CHUNKER_VERSION, ChunkConfig
from ai.chunking.ids import content_hash, make_chunk_id
from ai.chunking.models import BBoxEntry, ChildChunk, ChunkContext, ChunkReport
from ai.chunking.sections import Section
from ai.chunking.text import TextSplitter
from ai.chunking.tokens import TokenCounter
from ai.ingestion.models import BlockType, Document, PageContent


@dataclass(slots=True)
class Draft:
    """A chunk under construction."""

    atoms: list[Atom]
    section_ids: list[int]
    head_path: tuple[str, ...]
    titles: list[str]
    page_start: int
    page_end: int

    @property
    def tokens(self) -> int:
        return sum(a.tokens for a in self.atoms)

    @property
    def kinds(self) -> set[str]:
        return {a.kind for a in self.atoms}

    @property
    def isolated(self) -> bool:
        return bool(self.kinds & ISOLATED_KINDS)


def _common_prefix(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    out = []
    for x, y in zip(a, b, strict=False):  # common prefix: lengths differ
        if x != y:
            break
        out.append(x)
    return tuple(out)


class ChunkBuilder:
    """Builds :class:`ChildChunk` objects from sections."""

    def __init__(
        self,
        config: ChunkConfig,
        counter: TokenCounter,
        atoms: AtomBuilder,
        splitter: TextSplitter,
    ) -> None:
        self._config = config
        self._counter = counter
        self._atoms = atoms
        self._splitter = splitter

    def _count(self, text: str) -> int:
        return self._counter.count(text)

    # -------------------------------------------------------------------- API
    def build(
        self,
        sections: list[Section],
        document: Document,
        ctx: ChunkContext,
        report: ChunkReport,
    ) -> list[ChildChunk]:
        pages = {p.page_number: p for p in document.pages}
        drafts: list[Draft] = []
        for section in sections:
            drafts.extend(self._section_drafts(section, document.unit, pages, report))
        drafts = self._merge(drafts, document.unit, report)
        return self._finalise(drafts, document, ctx, pages, report)

    # ------------------------------------------------------------- packing
    def _section_drafts(
        self, section: Section, unit: str, pages: dict[int, PageContent], report: ChunkReport
    ) -> list[Draft]:
        cfg = self._config
        atoms = self._atoms.build(section.blocks, pages)
        if not atoms:
            # a slide that consists of its title only (divider) is not indexed
            if unit == "slide" and section.page not in report.skipped_slides:
                report.skipped_slides.append(section.page)
            return []

        if unit == "slide":
            body = [a for a in atoms if a.kind != "notes"]
            rich = any(a.kind in ("table", "image_ocr", "chart") for a in body)
            if sum(a.tokens for a in body) < cfg.slide_min_body_tokens and not rich:
                if body and section.page not in report.skipped_slides:
                    report.skipped_slides.append(section.page)
                atoms = [a for a in atoms if a.kind == "notes"]  # notes still carry content
                if not atoms:
                    return []

        drafts: list[Draft] = []
        current: list[Atom] = []
        used = 0

        def make(items: list[Atom]) -> Draft:
            pages_used = {b.page_number for a in items for b in a.blocks}
            return Draft(
                atoms=list(items),
                section_ids=[section.id],
                head_path=section.head_path,
                titles=[section.head_path[-1]] if section.head_path else [],
                page_start=min(pages_used),
                page_end=max(pages_used),
            )

        def flush() -> None:
            nonlocal used
            if current:
                drafts.append(make(current))
                current.clear()
                used = 0

        for atom in atoms:
            for piece in self._atoms.split(atom):
                isolate = piece.kind in ISOLATED_KINDS or (
                    piece.kind == "image_ocr" and unit != "slide"
                )
                if isolate:
                    flush()
                    drafts.append(make([piece]))
                    continue
                if current and (
                    used + piece.tokens > cfg.max_tokens
                    or (used + piece.tokens > cfg.target_tokens and used >= cfg.min_tokens)
                ):
                    flush()
                current.append(piece)
                used += piece.tokens
        flush()
        return drafts

    # --------------------------------------------------------------- merging
    def _can_merge(self, a: Draft, b: Draft, unit: str) -> bool:
        if a.isolated or b.isolated or "image_ocr" in a.kinds or "image_ocr" in b.kinds:
            return False
        if a.tokens + b.tokens > self._config.target_tokens:
            return False
        if unit == "slide" and a.page_end != b.page_start:
            return False
        # Top-level siblings are unrelated topics: merging them would leave an empty
        # heading_path, so only genuine siblings (shared non-empty parent) or a
        # section followed by its own sub-section are merged.
        same_parent = bool(a.head_path[:-1]) and a.head_path[:-1] == b.head_path[:-1]
        descendant = bool(a.head_path) and b.head_path[: len(a.head_path)] == a.head_path
        return same_parent or descendant

    def _merge(self, drafts: list[Draft], unit: str, report: ChunkReport) -> list[Draft]:
        cfg = self._config
        out: list[Draft] = []
        for draft in drafts:
            if out:
                prev = out[-1]
                small = prev.tokens < cfg.min_tokens or draft.tokens < cfg.min_tokens
                if small and self._can_merge(prev, draft, unit):
                    prev.atoms.extend(draft.atoms)
                    prev.section_ids.extend(s for s in draft.section_ids if s not in prev.section_ids)
                    prev.head_path = _common_prefix(prev.head_path, draft.head_path)
                    for title in draft.titles:
                        if title not in prev.titles:
                            prev.titles.append(title)
                    prev.page_end = max(prev.page_end, draft.page_end)
                    report.merged_chunks += 1
                    continue
            out.append(draft)
        return out

    # ------------------------------------------------------------- finalise
    @staticmethod
    def _kind(draft: Draft) -> str:
        kinds = draft.kinds
        for single in ("notes", "table", "chart", "image_ocr"):
            if kinds == {single}:
                return single
        return "mixed" if ("image_ocr" in kinds or "table" in kinds) else "text"

    @staticmethod
    def _source_kind(draft: Draft, pages: dict[int, PageContent]) -> str:
        kinds: set[str] = set()
        for atom in draft.atoms:
            if atom.kind == "image_ocr":
                kinds.add("image_ocr")
                continue
            page = pages.get(atom.blocks[0].page_number)
            kinds.add("ocr_page" if page is not None and page.ocr_applied else "native")
        return kinds.pop() if len(kinds) == 1 else "mixed"

    @staticmethod
    def _confidences(
        draft: Draft, pages: dict[int, PageContent], file_type: str
    ) -> tuple[float, float | None]:
        """``(overall confidence, lowest OCR confidence or None)`` for a draft."""
        overall: list[float] = []
        ocr: list[float] = []
        for atom in draft.atoms:
            for block in atom.blocks:
                page = pages.get(block.page_number)
                if block.type is BlockType.IMAGE_OCR and block.confidence is not None:
                    overall.append(block.confidence)
                    ocr.append(block.confidence)
                elif file_type == "pdf" and page is not None:
                    overall.append(page.confidence)
                    if page.ocr_applied:
                        ocr.append(page.confidence)
                else:
                    overall.append(1.0)  # office page confidence only describes images
        return (min(overall) if overall else 1.0), (min(ocr) if ocr else None)

    def _prefix(self, draft: Draft, unit: str, deck: str) -> str:
        if unit == "slide" and draft.head_path:
            lead = f"Slide {draft.page_start}: {draft.head_path[0]}"
            return f"{deck} | {lead}" if deck else lead
        if draft.head_path:
            return " > ".join(draft.head_path)
        return deck

    def _cap_tail(self, text: str, cap: int) -> str:
        """Keep the end of ``text`` (the most specific part of a path) within ``cap`` tokens."""
        if cap <= 0:
            return ""
        if not text or self._count(text) <= cap:
            return text
        words = text.split()
        for start in range(1, len(words)):
            candidate = "… " + " ".join(words[start:])
            if self._count(candidate) <= cap:
                return candidate
        return ""

    def _finalise(
        self,
        drafts: list[Draft],
        document: Document,
        ctx: ChunkContext,
        pages: dict[int, PageContent],
        report: ChunkReport,
    ) -> list[ChildChunk]:
        cfg = self._config
        source = document.source
        assert source is not None  # checked by the engine
        deck = source.title or ""
        chunks: list[ChildChunk] = []
        previous: tuple[Draft, str] | None = None

        for ordinal, draft in enumerate(drafts):
            kind = self._kind(draft)
            table = draft.atoms[0] if kind == "table" and len(draft.atoms) == 1 else None
            text = "\n\n".join(a.text for a in draft.atoms)
            body = "\n\n".join(a.embed for a in draft.atoms)

            # overlap: only between consecutive plain-text chunks of the same section
            overlap = ""
            if (
                previous is not None
                and kind == "text"
                and previous[1] == "text"
                and previous[0].section_ids[-1] == draft.section_ids[0]
            ):
                overlap = self._splitter.tail(
                    "\n\n".join(a.text for a in previous[0].atoms), cfg.overlap_tokens
                )

            prefix = self._cap_tail(self._prefix(draft, document.unit, deck), cfg.prefix_max_tokens)
            context = f"Context: {table.context}" if table is not None and table.context else ""

            # Fit under the hard limit by dropping optional parts, most expendable first:
            # overlap, then table context, then (as a last resort) all but the end of the prefix.
            attempts = [
                (overlap, context, prefix),
                ("", context, prefix),
                ("", "", prefix),
                ("", "", self._cap_tail(prefix, min(20, cfg.prefix_max_tokens))),
            ]
            for overlap, context, used_prefix in attempts:
                embedding_text = "\n".join(p for p in (used_prefix, context, overlap, body) if p)
                tokens = self._count(embedding_text)
                if tokens <= cfg.max_tokens:
                    break
            oversize = tokens > cfg.max_tokens
            if oversize:
                report.oversize_chunks += 1
                report.warnings.append(f"chunk {ordinal} exceeds max_tokens ({tokens})")

            blocks = [b for a in draft.atoms for b in a.blocks]
            orders = tuple(sorted({b.order for b in blocks}))
            block_types: list[str] = []
            for b in blocks:
                if b.type.value not in block_types:
                    block_types.append(b.type.value)
            bboxes: list[BBoxEntry] = []
            for b in blocks:
                if b.bbox is not None and len(bboxes) < cfg.max_bboxes:
                    bboxes.append((b.page_number, b.bbox))

            confidence, ocr_confidence = self._confidences(draft, pages, source.file_type)
            text_hash = content_hash(text)
            slide_no = draft.page_start if document.unit == "slide" else None

            chunks.append(
                ChildChunk(
                    chunk_id=make_chunk_id(source.doc_id, ordinal, text_hash),
                    ordinal=ordinal,
                    kind=kind,
                    text=text,
                    token_count=tokens,
                    content_hash=text_hash,
                    doc_id=source.doc_id,
                    document_uid=ctx.document_uid,
                    sha256=source.sha256,
                    file_name=source.file_name,
                    file_type=source.file_type,
                    unit=document.unit,
                    title=source.title,
                    author=source.author,
                    created=source.created,
                    modified=source.modified,
                    language=source.language,
                    ingested_at=source.ingested_at,
                    user_id=ctx.user_id,
                    course_id=ctx.course_id,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    slide_number=slide_no,
                    heading_path=draft.head_path,
                    section_titles=tuple(draft.titles) if len(draft.section_ids) > 1 else (),
                    block_start=orders[0],
                    block_end=orders[-1],
                    block_orders=orders,
                    block_ranges=block_ranges(orders),
                    block_types=tuple(block_types),
                    citation_label=citation_label(
                        document.unit, draft.page_start, draft.page_end, draft.head_path
                    ),
                    bboxes=tuple(bboxes),
                    confidence=confidence,
                    ocr_confidence=ocr_confidence,
                    low_confidence=confidence < cfg.low_confidence_page,
                    source_kind=self._source_kind(draft, pages),
                    chunker_version=CHUNKER_VERSION,
                    schema_version=document.schema_version,
                    tokenizer=self._counter.name,
                    parent_id="",  # assigned by ParentBuilder
                    embedding_text=embedding_text,
                    overlap_prefix=overlap,
                    embedding_hash=content_hash(embedding_text),
                    has_table=table is not None,
                    table_index=table.table_index if table is not None else None,
                    table_part=table.table_part if table is not None else None,
                    table_parts=table.table_parts if table is not None else None,
                    embedding_model=ctx.embedding_model,
                    oversize=oversize,
                )
            )
            previous = (draft, kind)
        return chunks

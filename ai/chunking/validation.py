"""ChunkValidator: checks the design invariants on a finished chunking result."""

from __future__ import annotations

from collections import Counter

from ai.chunking.config import ChunkConfig
from ai.chunking.ids import normalize_for_hash
from ai.chunking.models import ChildChunk, ChunkContext, ChunkReport, ParentChunk
from ai.chunking.selection import BlockSelector
from ai.ingestion.models import BlockType, Document


def _related(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """True when one heading path is a prefix of (or equal to) the other."""
    shorter = min(len(a), len(b))
    return a[:shorter] == b[:shorter]


class ChunkValidator:
    """Returns human-readable problems; an empty list means the result is consistent.

    Checked: coverage of selected blocks, unique ids, parent/child links, block order,
    token cap, slide purity, hidden-slide exclusion, heading-path ancestry, overlap rules,
    OCR confidence rules (< 0.3 never indexed, < 0.6 always flagged) and table headers.
    """

    def __init__(self, config: ChunkConfig, selector: BlockSelector | None = None) -> None:
        self._config = config
        self._selector = selector or BlockSelector(config)

    def validate(
        self,
        document: Document,
        children: list[ChildChunk],
        parents: list[ParentChunk] | None = None,
        *,
        ctx: ChunkContext | None = None,
        report: ChunkReport | None = None,
    ) -> list[str]:
        problems: list[str] = []
        self._coverage(document, children, report, problems)
        self._identity(children, parents, problems)
        self._per_child(document, children, ctx, problems)
        self._overlap(children, problems)
        self._table_headers(children, problems)
        if parents is not None:
            self._links(children, parents, problems)
        return problems

    # ---------------------------------------------------------------- checks
    def _coverage(
        self,
        document: Document,
        children: list[ChildChunk],
        report: ChunkReport | None,
        out: list[str],
    ) -> None:
        # slides skipped on purpose (title-only) are not expected to be covered, except notes
        skipped = set(report.skipped_slides) if report is not None else set()
        selected = [
            b
            for b in self._selector.select(document, ChunkReport())
            if b.type is not BlockType.HEADING
            and not (document.unit == "slide" and b.page_number in skipped and b.type is not BlockType.NOTES)
        ]
        covered = {order for c in children for order in c.block_orders}
        for block in selected:
            if block.order not in covered:
                out.append(f"block {block.order} ({block.type.value}) not covered by any chunk")

    @staticmethod
    def _identity(
        children: list[ChildChunk], parents: list[ParentChunk] | None, out: list[str]
    ) -> None:
        everyone = [c.chunk_id for c in children] + [p.chunk_id for p in parents or []]
        for chunk_id, count in Counter(everyone).items():
            if count > 1:
                out.append(f"duplicate chunk id {chunk_id} ({count}x)")

    def _per_child(
        self,
        document: Document,
        children: list[ChildChunk],
        ctx: ChunkContext | None,
        out: list[str],
    ) -> None:
        cfg = self._config
        by_order = {b.order: b for b in document.blocks}
        hidden = {
            int(s["slide_number"]) for s in document.metadata.get("slides", []) if s.get("hidden")
        }
        for chunk in children:
            label = f"chunk {chunk.ordinal} ({chunk.kind})"
            if list(chunk.block_orders) != sorted(set(chunk.block_orders)):
                out.append(f"{label}: block_orders not strictly increasing")
            if document.unit == "slide" and chunk.page_start != chunk.page_end:
                out.append(f"{label}: spans several slides")
            if document.unit == "slide" and chunk.page_start in hidden:
                out.append(f"{label}: content of hidden slide {chunk.page_start} is indexed")
            if chunk.token_count > cfg.max_tokens and not chunk.oversize:
                out.append(f"{label}: {chunk.token_count} tokens exceed max_tokens without oversize flag")
            if not chunk.citation_label:
                out.append(f"{label}: missing citation label")
            for order in chunk.block_orders:
                block = by_order.get(order)
                if block is None:
                    out.append(f"{label}: unknown block {order}")
                elif block.heading_path[: len(chunk.heading_path)] != chunk.heading_path:
                    out.append(f"{label}: heading_path is not an ancestor of block {order}")
            if chunk.ocr_confidence is not None and chunk.ocr_confidence < cfg.ocr_min_confidence:
                out.append(
                    f"{label}: OCR confidence {chunk.ocr_confidence:.2f} below "
                    f"{cfg.ocr_min_confidence} must not be indexed"
                )
            if chunk.confidence < cfg.low_confidence_page and not chunk.low_confidence:
                out.append(f"{label}: confidence {chunk.confidence:.2f} < "
                           f"{cfg.low_confidence_page} but low_confidence flag is missing")
            if ctx is not None and (
                chunk.document_uid != ctx.document_uid
                or chunk.user_id != ctx.user_id
                or chunk.course_id != ctx.course_id
            ):
                out.append(f"{label}: ownership does not match the chunking context")

    @staticmethod
    def _overlap(children: list[ChildChunk], out: list[str]) -> None:
        by_ordinal = {c.ordinal: c for c in children}
        for chunk in children:
            if not chunk.overlap_prefix:
                continue
            label = f"chunk {chunk.ordinal} ({chunk.kind})"
            if chunk.kind != "text":
                out.append(f"{label}: overlap is only allowed on text chunks")
                continue
            previous = by_ordinal.get(chunk.ordinal - 1)
            if previous is None or previous.kind != "text":
                out.append(f"{label}: overlap without a preceding text chunk")
            elif normalize_for_hash(chunk.overlap_prefix) not in normalize_for_hash(previous.text):
                out.append(f"{label}: overlap does not come from the preceding chunk")
            elif not _related(previous.heading_path, chunk.heading_path):
                # a merged chunk (common-prefix path) may continue into its last section
                out.append(f"{label}: overlap crosses a section boundary")

    @staticmethod
    def _table_headers(children: list[ChildChunk], out: list[str]) -> None:
        headers: dict[tuple[int, int | None], str] = {}
        for chunk in children:
            if chunk.kind != "table" or not chunk.table_parts:
                continue
            first_line = chunk.text.splitlines()[0] if chunk.text else ""
            # parts cut by columns (very wide rows) differ in the other headers but always
            # repeat the row-label header, i.e. the first cell
            first_cell = first_line.split("|")[1].strip() if first_line.count("|") >= 2 else first_line
            key = (chunk.block_start, chunk.table_index)
            if headers.setdefault(key, first_cell) != first_cell:
                out.append(f"chunk {chunk.ordinal}: table header not repeated in every part")

    @staticmethod
    def _links(children: list[ChildChunk], parents: list[ParentChunk], out: list[str]) -> None:
        by_id = {p.chunk_id: p for p in parents}
        child_ids = {c.chunk_id for c in children}
        for child in children:
            parent = by_id.get(child.parent_id)
            if parent is None:
                out.append(f"chunk {child.ordinal}: references missing parent {child.parent_id!r}")
            elif child.chunk_id not in parent.child_ids:
                out.append(f"chunk {child.ordinal}: not listed in child_ids of its parent")
        for parent in parents:
            for cid in parent.child_ids:
                if cid not in child_ids:
                    out.append(f"parent {parent.ordinal}: child_ids contains unknown chunk {cid}")

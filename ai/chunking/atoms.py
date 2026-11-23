"""Atoms: the smallest units the packer moves around, plus how oversize ones are split.

Final rules implemented here:

* headings are structural metadata and never become atoms;
* a list stays together (and keeps its introducing ``...:`` paragraph) whenever possible;
* tables, charts, speaker notes and OCR text are atomic - they are only split when they
  exceed the hard token limit (tables are split by rows with the header repeated);
* **the hard limit always wins**: a single list item, table row, table cell, chart or note
  that is larger than a chunk is split at sentence / cell / word boundaries instead of
  producing an oversize chunk.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai.chunking.config import ChunkConfig
from ai.chunking.render import to_key_value, to_markdown
from ai.chunking.text import TextSplitter
from ai.chunking.tokens import TokenCounter
from ai.ingestion.models import Block, BlockType, FigureData, PageContent
from ai.ingestion.structure import render_block

#: Atoms that always form a chunk of their own (never merged, never overlapped).
ISOLATED_KINDS = frozenset({"table", "notes", "chart", "figure"})
_LABELLED_KINDS = ("image_ocr", "notes", "chart")


@dataclass(slots=True)
class Atom:
    kind: str  # paragraph | list | table | chart | image_ocr | notes
    blocks: list[Block]
    text: str  # what users / the LLM see
    embed: str  # body used for embedding (differs from text only for tables)
    tokens: int
    units: list[tuple[str, list[Block]]] = field(default_factory=list)  # list items
    context: str = ""  # table: preceding short paragraph
    rows: list[list[str]] = field(default_factory=list)  # table rows (for row splitting)
    table_index: int | None = None
    table_part: int | None = None
    table_parts: int | None = None
    figure: FigureData | None = None  # figure atoms: the source record (caption, mentions ...)


class AtomBuilder:
    """Turns the blocks of a section into atoms and splits oversize atoms."""

    def __init__(self, config: ChunkConfig, counter: TokenCounter, splitter: TextSplitter) -> None:
        self._config = config
        self._counter = counter
        self._splitter = splitter

    def _count(self, text: str) -> int:
        return self._counter.count(text)

    # ------------------------------------------------------------------ build
    def build(self, blocks: list[Block], pages: dict[int, PageContent]) -> list[Atom]:
        atoms: list[Atom] = []
        i = 0
        while i < len(blocks):
            block = blocks[i]
            kind = block.type
            if kind is BlockType.HEADING:
                i += 1
                continue
            if kind is BlockType.LIST_ITEM:
                i = self._list_atom_from(blocks, i, atoms)
                continue
            if kind is BlockType.PARAGRAPH:
                atoms.append(Atom("paragraph", [block], block.text, block.text, self._count(block.text)))
            elif kind is BlockType.CHART:
                atoms.append(self._labelled("chart", "[Chart]", block))
            elif kind is BlockType.IMAGE_OCR:
                atoms.append(self._labelled("image_ocr", "[Image text]", block))
            elif kind is BlockType.NOTES:
                atoms.append(self._labelled("notes", "[Speaker Notes]", block))
            elif kind is BlockType.FIGURE:
                atoms.append(self._figure_atom(block, pages))
            elif kind is BlockType.TABLE:
                atoms.append(self._table_atom(block, pages, atoms))
            i += 1
        return atoms

    def _figure_atom(self, block: Block, pages: dict[int, PageContent]) -> Atom:
        """Caption, text inside the figure, the sentences that cite it and (later) a generated description.

        Fixed template so the answer layer can tell source text from generated text. Every part is clipped
        so the atom always fits one chunk: a figure is never split.
        """
        figure = None
        page = pages.get(block.page_number)
        if page is not None and block.ref_index is not None and 0 <= block.ref_index < len(page.figures):
            figure = page.figures[block.ref_index]
        if figure is None:  # figure record missing: use the block text as it is
            text = self._clip(f"[Figure]\n{block.text}", self._config.target_tokens)
            return Atom("figure", [block], text, text, self._count(text))
        budget = self._config.target_tokens
        parts = [f"[{figure.label or 'Figure'}]" + (f" (page {figure.page_number})" if figure.page_number else "")]
        if figure.caption:
            parts.append(self._clip(figure.caption if figure.caption.lower().startswith("fig") else f"Caption: {figure.caption}", budget // 3))
        elif figure.alt_text:
            parts.append(self._clip(f"Alt text: {figure.alt_text}", budget // 6))
        inner = figure.inner_text or figure.ocr_text
        if inner:
            parts.append(self._clip(f"Text in figure: {inner}", budget // 3))
        for sentence in figure.mentions[:2]:
            parts.append(self._clip(f'Discussed in text: "{sentence}"', budget // 8))
        if figure.description and figure.description_status == "done":
            parts.append(self._clip(f"Generated description (AI-generated, may contain errors): {figure.description}", budget // 4))
        text = "\n".join(parts)
        return Atom("figure", [block], text, text, self._count(text), figure=figure)

    def _clip(self, text: str, max_tokens: int) -> str:
        """``text`` cut at a word boundary to at most ``max_tokens`` (with an ellipsis when cut)."""
        if self._count(text) <= max_tokens:
            return text
        words = text.split()
        low, high = 1, len(words)
        while low < high:  # longest prefix that fits
            mid = (low + high + 1) // 2
            if self._count(" ".join(words[:mid]) + " ...") <= max_tokens:
                low = mid
            else:
                high = mid - 1
        return " ".join(words[:low]) + " ..."

    def _labelled(self, kind: str, label: str, block: Block) -> Atom:
        text = f"{label}\n{block.text}"
        return Atom(kind, [block], text, text, self._count(text))

    def _list_atom_from(self, blocks: list[Block], start: int, atoms: list[Atom]) -> int:
        end = start
        while end < len(blocks) and blocks[end].type is BlockType.LIST_ITEM:
            end += 1
        units = [(render_block(b), [b]) for b in blocks[start:end]]
        if (
            atoms
            and atoms[-1].kind == "paragraph"
            and atoms[-1].text.rstrip().endswith(":")
            and atoms[-1].blocks[-1] is blocks[start - 1]
        ):
            lead = atoms.pop()  # keep "The steps are:" together with its list
            units[0] = (f"{lead.text}\n{units[0][0]}", lead.blocks + units[0][1])
        atoms.append(self._list_atom(units))
        return end

    def _list_atom(self, units: list[tuple[str, list[Block]]]) -> Atom:
        text = "\n".join(u[0] for u in units)
        blocks = [b for _, bs in units for b in bs]
        return Atom("list", blocks, text, text, self._count(text), units=units)

    def _table_atom(self, block: Block, pages: dict[int, PageContent], previous: list[Atom]) -> Atom:
        rows = self._table_rows(block, pages)
        if rows:
            text, embed = to_markdown(rows), to_key_value(rows)
        else:  # table object missing: fall back to the reader's own rendering
            text = embed = block.text
        context = ""
        if previous and previous[-1].kind == "paragraph":
            candidate = previous[-1].text
            if self._count(candidate) <= self._config.context_max_tokens:
                context = candidate
        atom = Atom("table", [block], text, embed, self._count(embed), context=context)
        atom.table_index = block.ref_index
        atom.rows = rows
        return atom

    @staticmethod
    def _table_rows(block: Block, pages: dict[int, PageContent]) -> list[list[str]]:
        page = pages.get(block.page_number)
        if page is None:
            return []
        for table in page.tables:
            if table.index == block.ref_index:
                return [list(r) for r in table.rows]
        return []

    # ------------------------------------------------------------------ split
    def split(self, atom: Atom) -> list[Atom]:
        """Pieces of ``atom`` that fit the limits (usually just ``[atom]``)."""
        cfg = self._config
        if atom.kind == "table":
            return self._split_table(atom)
        if atom.kind == "figure":
            return [atom]  # already clipped to fit; a figure is one retrievable unit
        if atom.tokens <= cfg.max_tokens - cfg.overlap_tokens:
            return [atom]
        if atom.kind == "list":
            return self._split_list(atom)
        return self._split_prose(atom)

    def _split_list(self, atom: Atom) -> list[Atom]:
        limit = self._config.target_tokens
        parts: list[Atom] = []
        group: list[tuple[str, list[Block]]] = []
        used = 0

        def flush() -> None:
            nonlocal group, used
            if group:
                parts.append(self._list_atom(group))
                group, used = [], 0

        for unit in atom.units:
            tokens = self._count(unit[0])
            if tokens > limit:  # one item longer than a chunk: split it at sentence boundaries
                flush()
                parts.extend(self._list_atom([(piece, unit[1])]) for piece in self._splitter.split(unit[0], limit))
                continue
            if group and used + tokens > limit:
                flush()
            group.append(unit)
            used += tokens
        flush()
        return parts

    def _split_prose(self, atom: Atom) -> list[Atom]:
        label, body = "", atom.text
        if atom.kind in _LABELLED_KINDS:
            label, _, body = atom.text.partition("\n")
        out: list[Atom] = []
        for piece in self._splitter.split(body, self._config.target_tokens):
            text = f"{label}\n{piece}" if label else piece
            out.append(Atom(atom.kind, atom.blocks, text, text, self._count(text)))
        return out or [atom]

    # ------------------------------------------------------------------ tables
    def _table_part(self, template: Atom, rows: list[list[str]]) -> Atom:
        embed = to_key_value(rows)
        part = Atom("table", template.blocks, to_markdown(rows), embed, self._count(embed))
        part.table_index = template.table_index
        part.rows = rows
        return part

    def _split_table(self, atom: Atom) -> list[Atom]:
        cfg = self._config
        rows = atom.rows
        if atom.tokens <= cfg.table_max_tokens:
            return [atom]

        parts: list[Atom] = []
        if len(rows) < 2:  # no data rows to split by: cut the text itself
            for piece in self._splitter.split(atom.embed, cfg.target_tokens):
                part = Atom("table", atom.blocks, piece, piece, self._count(piece))
                part.table_index = atom.table_index
                parts.append(part)
        else:
            header, data = rows[0], rows[1:]
            group: list[list[str]] = []
            for row in data:
                if self._count(to_key_value([header, row])) > cfg.target_tokens:
                    # a single row (with its header) is bigger than a chunk: split by cells
                    if group:
                        parts.append(self._table_part(atom, [header, *group]))
                        group = []
                    parts.extend(self._wide_row_parts(atom, header, row))
                    continue
                if group and self._count(to_key_value([header, *group, row])) > cfg.target_tokens:
                    parts.append(self._table_part(atom, [header, *group]))
                    group = []
                group.append(row)
            if group:
                parts.append(self._table_part(atom, [header, *group]))

        for number, part in enumerate(parts, start=1):
            part.table_part, part.table_parts = number, len(parts)
            if number == 1:
                part.context = atom.context
        return parts or [atom]

    def _wide_row_parts(self, template: Atom, header: list[str], row: list[str]) -> list[Atom]:
        """Split one oversize row into column groups, repeating the row label (first column).

        A single cell larger than half a chunk is itself cut at sentence/word boundaries.
        """
        cfg = self._config
        width = max(len(header), len(row))
        header = [*header, *[""] * (width - len(header))]
        row = [*row, *[""] * (width - len(row))]
        label_header, label_value = header[0], row[0]
        cell_limit = max(cfg.target_tokens // 2, 1)

        cells: list[tuple[str, str]] = []
        for head, value in zip(header[1:], row[1:], strict=True):
            if self._count(value) > cell_limit:
                cells.extend((head, piece) for piece in self._splitter.split(value, cell_limit))
            else:
                cells.append((head, value))

        def as_rows(group: list[tuple[str, str]]) -> list[list[str]]:
            return [[label_header, *[h for h, _ in group]], [label_value, *[v for _, v in group]]]

        parts: list[Atom] = []
        current: list[tuple[str, str]] = []
        for cell in cells:
            if current and self._count(to_key_value(as_rows([*current, cell]))) > cfg.target_tokens:
                parts.append(self._table_part(template, as_rows(current)))
                current = []
            current.append(cell)
        if current:
            parts.append(self._table_part(template, as_rows(current)))
        return parts

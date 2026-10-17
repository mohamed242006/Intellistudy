"""Seeded random documents for property-style tests (no extra dependency).

``random_document(seed)`` returns a schema-2.0 ``Document`` with headings of mixed depth,
paragraphs of widely varying length, lists, tables, charts, OCR text, speaker notes and
(for slides) hidden slides. Every paragraph word is unique (``p<block>_<n>``), which lets
tests prove that no word is lost or duplicated by chunking.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from ai.ingestion.models import Block, BlockType, Document, PageContent, SourceInfo, TableData
from ai.ingestion.structure import finalize_document


@dataclass
class RandomDoc:
    document: Document
    unique_words: set[str] = field(default_factory=set)  # words that must survive exactly once
    hidden_slides: set[int] = field(default_factory=set)


def _words(rnd: random.Random, tag: str, n: int) -> list[str]:
    return [f"{tag}_{i}" for i in range(n)]


def random_document(
    seed: int,
    *,
    unit: str = "page",
    sections: int = 8,
    max_paragraph: int = 300,
    tables: bool = True,
) -> RandomDoc:
    rnd = random.Random(seed)
    file_type = {"page": "pdf", "slide": "pptx", "document": "docx"}[unit]
    blocks: list[Block] = []
    pages: dict[int, PageContent] = {}
    unique: set[str] = set()
    hidden: set[int] = set()
    counter = 0

    def page_for(number: int) -> PageContent:
        return pages.setdefault(number, PageContent(page_number=number))

    page_number = 1
    for s in range(sections):
        if unit == "slide":
            page_number = s + 1
            if s > 0 and rnd.random() < 0.15:
                hidden.add(page_number)
        elif unit == "page" and rnd.random() < 0.4:
            page_number += 1
        elif unit == "document":
            page_number = 1
        page_for(page_number)

        level = 1 if unit == "slide" else rnd.choice([1, 1, 2, 2, 3, 4])
        blocks.append(Block(BlockType.HEADING, f"Section {s} topic{rnd.randint(0, 9)}", page_number, level=level))

        for _ in range(rnd.randint(0, 6)):
            kind = rnd.choices(["para", "list", "table", "ocr", "chart", "notes"], weights=[8, 3, 2, 1, 1, 1])[0]
            counter += 1
            if kind == "para":
                n = rnd.choice([3, 8, 20, 60, 150, max_paragraph])
                words = _words(rnd, f"p{counter}", n)
                # sentences of random length so the splitter has boundaries to use
                text, i = [], 0
                while i < n:
                    step = rnd.randint(4, 25)
                    text.append(" ".join(words[i : i + step]) + ".")
                    i += step
                unique.update(words)
                blocks.append(Block(BlockType.PARAGRAPH, " ".join(text).replace("..", "."), page_number))
            elif kind == "list":
                for j in range(rnd.randint(1, 8)):
                    words = _words(rnd, f"l{counter}x{j}", rnd.randint(2, 25))
                    unique.update(words)
                    blocks.append(Block(BlockType.LIST_ITEM, " ".join(words), page_number,
                                        level=rnd.choice([0, 0, 1]), list_marker="-"))
            elif kind == "table" and tables:
                page = page_for(page_number)
                rows = [[f"H{c}" for c in range(rnd.randint(2, 4))]]
                for r in range(rnd.randint(1, 40)):
                    rows.append([f"t{counter}r{r}c{c}" for c in range(len(rows[0]))])
                index = len(page.tables)
                page.tables.append(TableData(page_number=page_number, index=index, rows=rows))
                blocks.append(Block(BlockType.TABLE, "table", page_number, ref_index=index))
            elif kind == "ocr":
                words = _words(rnd, f"o{counter}", rnd.randint(5, 80))
                unique.update(words)
                blocks.append(Block(BlockType.IMAGE_OCR, " ".join(words), page_number,
                                    ref_index=0, confidence=rnd.choice([0.95, 0.8, 0.65, 0.5, 0.4])))
            elif kind == "chart":
                words = _words(rnd, f"c{counter}", rnd.randint(4, 30))
                unique.update(words)
                blocks.append(Block(BlockType.CHART, "Title: " + " ".join(words), page_number))
            elif kind == "notes" and unit == "slide":
                words = _words(rnd, f"n{counter}", rnd.randint(3, 120))
                unique.update(words)
                blocks.append(Block(BlockType.NOTES, " ".join(words), page_number))

    source = SourceInfo(
        doc_id=f"r{seed:015d}", sha256="0" * 64, file_name=f"random-{seed}.{file_type}",
        file_type=file_type, file_size_bytes=1, unit=unit, page_count=len(pages),
        title=f"Random {seed}", ingested_at="2026-01-01T00:00:00+00:00",
    )
    metadata = {}
    if unit == "slide":
        metadata["slides"] = [
            {"slide_number": n, "title": f"S{n}", "has_notes": False, "hidden": n in hidden}
            for n in sorted(pages)
        ]
    for b in blocks:
        pages[b.page_number].blocks.append(b)
    document = Document(source_path=f"random-{seed}", pages=[pages[n] for n in sorted(pages)],
                        metadata=metadata, source=source)
    finalize_document(document, carry_across_pages=(unit != "slide"))
    return RandomDoc(document=document, unique_words=unique, hidden_slides=hidden)

"""Helpers that build small text PDFs (with optional bookmarks, headers, footers)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pymupdf as fitz

BODY_SIZE = 11.0
PAGE_HEIGHT = 842.0

BODY_LINES = [
    "This sentence is plain body text that fills the page nicely.",
    "A second body sentence keeps the page above the OCR threshold.",
    "A third line of ordinary prose follows the previous two lines.",
]


def make_pdf(
    path: Path,
    pages: list[list[tuple[str, float]]],
    toc: list[list[object]] | None = None,
    leading: float = 1.8,
    header: str | None = None,
    footer: str | None = None,
    start_y: float = 72.0,
) -> Path:
    """Create a PDF; each page is a list of ``(text, font_size)`` lines.

    Args:
        leading: baseline-to-baseline distance as a multiple of the font size.
        header: text drawn near the top of every page (``{n}`` / ``{total}``
            are replaced by page number and page count).
        footer: same, near the bottom.
    """
    document = fitz.open()
    total = len(pages)
    for number, lines in enumerate(pages, start=1):
        page = document.new_page()
        y = start_y
        for text, size in lines:
            page.insert_text((72, y), text, fontsize=size)
            y += size * leading
        values = {"n": number, "total": total}
        if header:
            page.insert_text((72, 30), header.format(**values), fontsize=9)
        if footer:
            page.insert_text((72, PAGE_HEIGHT - 30), footer.format(**values), fontsize=9)
    if toc:
        document.set_toc(toc)
    document.save(str(path))
    document.close()
    return path


def make_custom_pdf(path: Path, draw: Callable[[fitz.Page, int], None], pages: int = 1) -> Path:
    """Create a PDF whose pages are drawn by ``draw(page, page_number)``."""
    document = fitz.open()
    for number in range(1, pages + 1):
        draw(document.new_page(), number)
    document.save(str(path))
    document.close()
    return path


def body(*extra: str) -> list[tuple[str, float]]:
    """Body-size lines (the default sentences plus any ``extra`` ones)."""
    return [(text, BODY_SIZE) for text in (*BODY_LINES, *extra)]

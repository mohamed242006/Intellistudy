"""Citation labels and block-range helpers shared by child and parent chunks."""

from __future__ import annotations

from collections.abc import Iterable


def citation_label(unit: str, page_start: int, page_end: int, path: tuple[str, ...]) -> str:
    """Human-readable location: ``p. 4-5 > A > B`` / ``slide 7 > A`` / ``A > B`` (DOCX)."""
    if unit == "page":
        where = f"p. {page_start}" if page_start == page_end else f"p. {page_start}-{page_end}"
    elif unit == "slide":
        where = f"slide {page_start}" if page_start == page_end else f"slides {page_start}-{page_end}"
    else:
        where = ""
    trail = " > ".join(path)
    return " > ".join(part for part in (where, trail) if part) or "document"


def block_ranges(orders: Iterable[int]) -> tuple[tuple[int, int], ...]:
    """Collapse block orders into inclusive contiguous ranges: (3,4,5,7) -> ((3,5),(7,7))."""
    ranges: list[tuple[int, int]] = []
    for order in sorted(set(orders)):
        if ranges and order == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], order)
        else:
            ranges.append((order, order))
    return tuple(ranges)


def format_ranges(ranges: Iterable[tuple[int, int]]) -> str:
    """``((1, 2), (5, 5))`` -> ``"1-2,5-5"`` (flat form for vector-store metadata)."""
    return ",".join(f"{start}-{end}" for start, end in ranges)

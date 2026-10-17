"""Sections: runs of blocks under one leaf ``heading_path`` (a slide is always its own section)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ai.ingestion.models import Block, BlockType


@dataclass(slots=True)
class Section:
    id: int
    head_path: tuple[str, ...]
    page: int
    blocks: list[Block] = field(default_factory=list)


def build_sections(blocks: list[Block], unit: str) -> list[Section]:
    """A heading starts a new section; for slides every slide change does too."""
    sections: list[Section] = []
    current: Section | None = None
    for block in blocks:
        starts_new = (
            current is None
            or block.type is BlockType.HEADING
            or (unit == "slide" and block.page_number != current.page)
        )
        if starts_new:
            current = Section(id=len(sections), head_path=block.heading_path, page=block.page_number)
            sections.append(current)
        assert current is not None
        current.blocks.append(block)
    return sections

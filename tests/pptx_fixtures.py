"""Helpers that build small PPTX decks and a fake OCR engine for the tests."""

from __future__ import annotations

import copy
import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.oxml.ns import qn
from pptx.util import Inches

LAYOUT_TITLE_AND_CONTENT = 1
LAYOUT_TITLE_ONLY = 5
LAYOUT_BLANK = 6


class FakeOCR:
    """Stand-in for :class:`OCRProcessor`; counts calls and returns fixed text."""

    def __init__(self, text: str = "LOGO TEXT", confidence: float = 90.0) -> None:
        self.calls = 0
        self._text = text
        self._confidence = confidence

    def process_image(self, image: Image.Image, cache_key: object | None = None):
        self.calls += 1
        return SimpleNamespace(
            text=self._text, confidence=self._confidence, applied=True, skipped_reason=None
        )


def png_bytes(color: str = "white", size: tuple[int, int] = (200, 80)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


def add_picture(slide, directory: Path, name: str, color: str = "white", top: float = 1.0):
    path = directory / name
    path.write_bytes(png_bytes(color))
    return slide.shapes.add_picture(str(path), Inches(5), Inches(top), Inches(1), Inches(1))


def blank_presentation() -> Presentation:
    return Presentation()


def add_bullet_slide(prs: Presentation, title: str, items: list[tuple[str, int]]):
    """Title + body placeholder; ``items`` is ``[(text, level), ...]``."""
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE_AND_CONTENT])
    slide.shapes.title.text = title
    frame = slide.placeholders[1].text_frame
    for position, (text, level) in enumerate(items):
        paragraph = frame.paragraphs[0] if position == 0 else frame.add_paragraph()
        paragraph.text = text
        paragraph.level = level
    return slide


def make_numbered(paragraph, scheme: str = "arabicPeriod") -> None:
    """Mark a paragraph as an auto-numbered list item."""
    props = paragraph._p.get_or_add_pPr()
    for child in list(props):
        if child.tag in (qn("a:buNone"), qn("a:buChar"), qn("a:buAutoNum")):
            props.remove(child)
    bullet = props.makeelement(qn("a:buAutoNum"), {"type": scheme})
    props.append(bullet)


def add_chart_slide(prs: Presentation, title: str = "Results", chart_title: str | None = "Student Performance"):
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE_ONLY])
    slide.shapes.title.text = title
    data = CategoryChartData()
    data.categories = ["Exam 1", "Exam 2", "Final"]
    data.add_series("Class A", (1, 2, 3))
    data.add_series("Class B", (2, 3, 4))
    frame = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.5), Inches(1.5), Inches(4), Inches(3), data
    )
    chart = frame.chart
    if chart_title:
        chart.has_title = True
        chart.chart_title.text_frame.text = chart_title
    chart.has_legend = True
    chart.value_axis.has_title = True
    chart.value_axis.axis_title.text_frame.text = "Score"
    return slide


def add_merged_table_slide(prs: Presentation):
    """Header ``Group | Scores(merged x2)``; body rows A and B."""
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE_ONLY])
    slide.shapes.title.text = "Table"
    table = slide.shapes.add_table(3, 3, Inches(0.5), Inches(2), Inches(6), Inches(1.5)).table
    table.cell(0, 0).text = "Group"
    table.cell(0, 1).text = "Scores"
    table.cell(0, 1).merge(table.cell(0, 2))
    for row, (name, left, right) in enumerate([("A", "1", "2"), ("B", "3", "4")], start=1):
        table.cell(row, 0).text = name
        table.cell(row, 1).text = left
        table.cell(row, 2).text = right
    return slide


def add_vertical_merge_slide(prs: Presentation):
    """First column merged over both body rows: ``Topic`` spans rows 1-2."""
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE_ONLY])
    slide.shapes.title.text = "Vertical"
    table = slide.shapes.add_table(3, 2, Inches(0.5), Inches(2), Inches(6), Inches(1.5)).table
    table.cell(0, 0).text = "Topic"
    table.cell(0, 1).text = "Point"
    table.cell(1, 0).text = "Networks"
    table.cell(1, 0).merge(table.cell(2, 0))
    table.cell(1, 1).text = "TCP"
    table.cell(2, 1).text = "UDP"
    return slide


def add_grouped_title_slide(prs: Presentation, title: str = "Grouped Title"):
    """Blank slide whose only title placeholder lives inside a group shape."""
    donor = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE_ONLY])
    donor.shapes.title.text = title
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_BLANK])
    group = slide.shapes.add_group_shape()
    box = group.shapes.add_textbox(Inches(1), Inches(2), Inches(3), Inches(1))
    box.text_frame.text = "Grouped body"
    group._element.append(copy.deepcopy(donor.shapes.title._element))
    return slide


def save(prs: Presentation, directory: Path, name: str = "deck.pptx") -> Path:
    path = directory / name
    prs.save(str(path))
    return path

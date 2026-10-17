"""Canonical schema contract: PDF, DOCX and PPTX must look the same to consumers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from docx import Document as new_docx

from ai.ingestion.docs_reader import DocxReader
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.ingestion.models import SCHEMA_VERSION, Block, BlockType, Document
from ai.ingestion.pptx_reader import PptxReader
from ai.ingestion.structure import (
    citation_label,
    parse_markdown_blocks,
    render_blocks,
)
from tests import pdf_fixtures as pf
from tests import pptx_fixtures as fx

CANONICAL_STATISTICS = {
    "page_count",
    "unit",
    "block_count",
    "heading_count",
    "list_item_count",
    "table_count",
    "image_count",
    "image_ocr_count",
    "chart_count",
    "total_characters",
    "average_confidence",
    "low_confidence_pages",
    "warning_count",
}
CANONICAL_METADATA = {
    "doc_id",
    "sha256",
    "file_name",
    "file_type",
    "file_size_bytes",
    "unit",
    "page_count",
    "parser",
    "ingested_at",
    "schema_version",
}


class SchemaTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        ocr = fx.FakeOCR()
        self.pipeline = IngestionPipeline(
            pptx_reader=PptxReader(ocr_processor=ocr),  # type: ignore[arg-type]
            docx_reader=DocxReader(ocr_processor=ocr),  # type: ignore[arg-type]
        )

    # -- builders ---------------------------------------------------------- #
    def pdf(self, name: str = "lecture.pdf", toc=None, pages=None) -> Path:
        pages = pages or [
            [("Chapter One", 24.0), ("Basics", 16.0), *pf.body()],
            pf.body("A paragraph that continues on the second page."),
        ]
        return pf.make_pdf(self.dir / name, pages, toc=toc)

    def docx(self, name: str = "notes.docx") -> Path:
        document = new_docx()
        document.add_heading("Notes", 1)
        document.add_paragraph("Body text of the notes.")
        document.add_paragraph("point", style="List Bullet")
        table = document.add_table(rows=2, cols=2)
        for r in range(2):
            for c in range(2):
                table.cell(r, c).text = f"r{r}c{c}"
        path = self.dir / name
        document.save(str(path))
        return path

    def pptx(self, name: str = "deck.pptx") -> Path:
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "Slide One", [("Main", 0), ("Sub", 1)])
        fx.add_chart_slide(prs, "Slide Two")
        return fx.save(prs, self.dir, name)

    def all_documents(self) -> dict[str, Document]:
        return {
            "pdf": self.pipeline.ingest(self.pdf()),
            "docx": self.pipeline.ingest(self.docx()),
            "pptx": self.pipeline.ingest(self.pptx()),
        }


class CrossFormatContractTests(SchemaTestCase):
    def test_canonical_statistics_exist_for_every_format(self) -> None:
        for kind, doc in self.all_documents().items():
            with self.subTest(kind=kind):
                self.assertTrue(CANONICAL_STATISTICS <= set(doc.statistics), kind)

    def test_canonical_metadata_exists_for_every_format(self) -> None:
        for kind, doc in self.all_documents().items():
            with self.subTest(kind=kind):
                self.assertTrue(CANONICAL_METADATA <= set(doc.metadata), kind)
                self.assertEqual(doc.metadata["file_type"], kind)
                self.assertEqual(doc.metadata["schema_version"], SCHEMA_VERSION)

    def test_source_info_is_filled(self) -> None:
        units = {"pdf": "page", "docx": "document", "pptx": "slide"}
        for kind, doc in self.all_documents().items():
            with self.subTest(kind=kind):
                assert doc.source is not None
                self.assertEqual(doc.source.file_type, kind)
                self.assertEqual(doc.source.unit, units[kind])
                self.assertEqual(len(doc.source.sha256), 64)
                self.assertEqual(doc.source.doc_id, doc.source.sha256[:16])
                self.assertEqual(doc.source.page_count, len(doc.pages))
                self.assertTrue(doc.source.parser)
                self.assertEqual(doc.statistics["page_count"], len(doc.pages))

    def test_blocks_are_globally_ordered_and_typed(self) -> None:
        for kind, doc in self.all_documents().items():
            with self.subTest(kind=kind):
                blocks = doc.blocks
                self.assertTrue(blocks)
                self.assertEqual([b.order for b in blocks], list(range(len(blocks))))
                valid_pages = {p.page_number for p in doc.pages}
                for block in blocks:
                    self.assertIsInstance(block.type, BlockType)
                    self.assertIn(block.page_number, valid_pages)
                    self.assertTrue(block.text.strip())
                self.assertEqual(doc.statistics["block_count"], len(blocks))

    def test_blocks_are_json_serialisable(self) -> None:
        for kind, doc in self.all_documents().items():
            with self.subTest(kind=kind):
                json.dumps([b.to_dict() for b in doc.blocks])
                json.dumps(doc.statistics)

    def test_marker_vocabulary_is_shared(self) -> None:
        docs = self.all_documents()
        self.assertIn("[Table 1]", docs["docx"].full_text)
        self.assertIn("[Chart]", docs["pptx"].full_text)
        self.assertIn("[Slide 1]", docs["pptx"].full_text)
        self.assertIn("[Page 1]", docs["pdf"].full_text)
        self.assertIn("[Document]", docs["docx"].full_text)


class PdfStructureTests(SchemaTestCase):
    def test_headings_get_levels_from_font_size(self) -> None:
        doc = self.pipeline.ingest(self.pdf())

        headings = [(b.text, b.level) for b in doc.blocks if b.is_heading]
        self.assertEqual(headings, [("Chapter One", 1), ("Basics", 2)])

    def test_heading_path_carries_across_pages(self) -> None:
        doc = self.pipeline.ingest(self.pdf())

        page_two = [b for b in doc.blocks if b.page_number == 2]
        self.assertTrue(page_two)
        for block in page_two:
            self.assertEqual(block.heading_path, ("Chapter One", "Basics"))

    def test_bookmark_outline_overrides_font_size_levels(self) -> None:
        pages = [[("Part A", 16.0), ("Part B", 16.0), *pf.body()]]
        toc = [[1, "Part A", 1], [2, "Part B", 1]]
        doc = self.pipeline.ingest(self.pdf("outlined.pdf", toc=toc, pages=pages))

        headings = [(b.text, b.level, b.heading_path) for b in doc.blocks if b.is_heading]
        self.assertEqual(
            headings,
            [("Part A", 1, ("Part A",)), ("Part B", 2, ("Part A", "Part B"))],
        )
        self.assertIn("## Part B", doc.pages[0].final_text)
        self.assertEqual(doc.metadata["outline"][0][1], "Part A")

    def test_pdf_dates_become_iso_strings(self) -> None:
        doc = self.pipeline.ingest(self.pdf())

        assert doc.source is not None
        if doc.source.created:
            self.assertRegex(doc.source.created, r"^\d{4}-\d{2}-\d{2}T")


class PptxStructureTests(SchemaTestCase):
    def test_heading_path_resets_on_every_slide(self) -> None:
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "First", [("a", 0)])
        slide = prs.slides.add_slide(prs.slide_layouts[fx.LAYOUT_BLANK])
        box = slide.shapes.add_textbox(0, 0, 914400, 914400)
        box.text_frame.text = "Orphan text on a slide without a title"
        doc = self.pipeline.ingest(fx.save(prs, self.dir, "reset.pptx"))

        orphan = next(b for b in doc.blocks if b.text.startswith("Orphan"))
        self.assertEqual(orphan.heading_path, ())
        first = next(b for b in doc.blocks if b.text == "a")
        self.assertEqual(first.heading_path, ("First",))

    def test_slide_blocks_follow_reading_order(self) -> None:
        doc = self.pipeline.ingest(self.pptx())

        slide_two = [b.type for b in doc.blocks if b.page_number == 2]
        self.assertEqual(slide_two, [BlockType.HEADING, BlockType.CHART])

    def test_notes_block_is_last_on_the_slide(self) -> None:
        prs = fx.blank_presentation()
        slide = fx.add_bullet_slide(prs, "T", [("point", 0)])
        slide.notes_slide.notes_text_frame.text = "Say this out loud"
        doc = self.pipeline.ingest(fx.save(prs, self.dir, "notes.pptx"))

        self.assertEqual(doc.blocks[-1].type, BlockType.NOTES)
        self.assertEqual(doc.blocks[-1].text, "Say this out loud")


class HelperTests(unittest.TestCase):
    def test_parse_markdown_blocks(self) -> None:
        text = "# Title\n\nFirst line\nsecond line\n\n- item\n  - nested\n\n## Sub"
        blocks = parse_markdown_blocks(text, page_number=3)

        self.assertEqual(
            [(b.type.value, b.text, b.level) for b in blocks],
            [
                ("heading", "Title", 1),
                ("paragraph", "First line\nsecond line", None),
                ("list_item", "item", 0),
                ("list_item", "nested", 1),
                ("heading", "Sub", 2),
            ],
        )
        self.assertTrue(all(b.page_number == 3 for b in blocks))

    def test_render_round_trips_structure(self) -> None:
        text = "# Title\n\nBody paragraph\n\n- one\n  - two"
        self.assertEqual(render_blocks(parse_markdown_blocks(text, 1)), text)

    def test_render_adds_labels_for_non_text_blocks(self) -> None:
        blocks = [
            Block(BlockType.TABLE, "A: 1", 1, ref_index=1),
            Block(BlockType.IMAGE_OCR, "words", 1, ref_index=0),
            Block(BlockType.CHART, "Title: X", 1),
            Block(BlockType.NOTES, "remember", 1),
        ]
        self.assertEqual(
            render_blocks(blocks),
            "[Table 2]\nA: 1\n\n[Embedded Image 1 OCR]\nwords\n\n[Chart]\nTitle: X\n\n"
            "[Speaker Notes]\nremember",
        )

    def test_citation_labels(self) -> None:
        block = Block(BlockType.PARAGRAPH, "x", 4, heading_path=("Caching", "LRU"))

        self.assertEqual(citation_label(block, "page"), "p. 4 > Caching > LRU")
        self.assertEqual(citation_label(block, "slide"), "slide 4 > Caching > LRU")
        self.assertEqual(citation_label(block, "document"), "Caching > LRU")
        self.assertEqual(citation_label(Block(BlockType.PARAGRAPH, "x", 1), "document"), "document")


if __name__ == "__main__":
    unittest.main()

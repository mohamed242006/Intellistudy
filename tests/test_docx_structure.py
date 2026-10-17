"""DOCX body-order, list and block tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from docx import Document as new_docx
from docx.shared import Inches

from ai.ingestion.docs_reader import DocxReader
from ai.ingestion.models import BlockType
from tests import pptx_fixtures as fx


class DocxStructureTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.ocr = fx.FakeOCR()
        self.reader = DocxReader(ocr_processor=self.ocr)  # type: ignore[arg-type]

    def read(self, document):
        path = self.dir / "doc.docx"
        document.save(str(path))
        return self.reader.read(path)


class BodyOrderTests(DocxStructureTestCase):
    def test_paragraphs_and_tables_keep_their_original_order(self) -> None:
        document = new_docx()
        document.add_heading("Chapter 1", 1)
        document.add_paragraph("Before the table.")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Name"
        table.cell(0, 1).text = "Value"
        table.cell(1, 0).text = "alpha"
        table.cell(1, 1).text = "1"
        document.add_paragraph("After the table.")
        document.add_heading("Chapter 2", 1)
        document.add_paragraph("Second chapter.")
        doc = self.read(document)

        kinds = [(b.type.value, b.text.split("\n")[0]) for b in doc.blocks]
        self.assertEqual(
            kinds,
            [
                ("heading", "Chapter 1"),
                ("paragraph", "Before the table."),
                ("table", "Name: alpha"),
                ("paragraph", "After the table."),
                ("heading", "Chapter 2"),
                ("paragraph", "Second chapter."),
            ],
        )
        final = doc.pages[0].final_text
        self.assertLess(final.index("Before the table."), final.index("[Table 1]"))
        self.assertLess(final.index("[Table 1]"), final.index("After the table."))
        self.assertLess(final.index("After the table."), final.index("# Chapter 2"))

    def test_image_ocr_appears_at_its_paragraph(self) -> None:
        picture = self.dir / "fig.png"
        picture.write_bytes(fx.png_bytes())
        document = new_docx()
        document.add_paragraph("Intro text.")
        document.add_picture(str(picture), width=Inches(1))
        document.add_paragraph("Text after the figure.")
        doc = self.read(document)

        final = doc.pages[0].final_text
        self.assertLess(final.index("Intro text."), final.index("[Embedded Image 1 OCR]"))
        self.assertLess(final.index("[Embedded Image 1 OCR]"), final.index("Text after"))
        image_blocks = [b for b in doc.blocks if b.type is BlockType.IMAGE_OCR]
        self.assertEqual(len(image_blocks), 1)
        self.assertEqual(image_blocks[0].ref_index, 0)


class ListTests(DocxStructureTestCase):
    def test_bullets_and_numbers_become_list_items(self) -> None:
        document = new_docx()
        document.add_paragraph("Shopping", style="List Bullet")
        document.add_paragraph("Nested", style="List Bullet 2")
        document.add_paragraph("First", style="List Number")
        document.add_paragraph("Second", style="List Number")
        doc = self.read(document)

        items = [b for b in doc.blocks if b.type is BlockType.LIST_ITEM]
        self.assertEqual([(i.text, i.level, i.list_marker) for i in items], [
            ("Shopping", 0, "-"),
            ("Nested", 1, "-"),
            ("First", 0, "1."),
            ("Second", 0, "2."),
        ])
        text = doc.pages[0].text
        self.assertIn("- Shopping\n  - Nested", text)
        self.assertIn("1. First\n2. Second", text)

    def test_heading_restarts_numbering(self) -> None:
        document = new_docx()
        document.add_paragraph("a", style="List Number")
        document.add_paragraph("b", style="List Number")
        document.add_heading("Next part", 1)
        document.add_paragraph("c", style="List Number")
        doc = self.read(document)

        markers = [b.list_marker for b in doc.blocks if b.type is BlockType.LIST_ITEM]
        self.assertEqual(markers, ["1.", "2.", "1."])

    def test_list_marker_does_not_leak_into_paragraphs(self) -> None:
        document = new_docx()
        document.add_paragraph("Plain sentence.")
        doc = self.read(document)

        self.assertEqual(doc.blocks[0].type, BlockType.PARAGRAPH)
        self.assertIsNone(doc.blocks[0].list_marker)


class HeadingPathTests(DocxStructureTestCase):
    def test_heading_path_follows_the_outline(self) -> None:
        document = new_docx()
        document.add_heading("Course Notes", 0)
        document.add_heading("Chapter 1", 1)
        document.add_heading("Caching", 2)
        document.add_paragraph("LRU evicts the oldest entry.")
        document.add_heading("Chapter 2", 1)
        document.add_paragraph("Networking basics.")
        doc = self.read(document)

        paths = {b.text: b.heading_path for b in doc.blocks}
        self.assertEqual(paths["Chapter 1"], ("Course Notes", "Chapter 1"))
        self.assertEqual(
            paths["LRU evicts the oldest entry."], ("Course Notes", "Chapter 1", "Caching")
        )
        self.assertEqual(paths["Networking basics."], ("Course Notes", "Chapter 2"))

    def test_paragraph_before_any_heading_has_empty_path(self) -> None:
        document = new_docx()
        document.add_paragraph("Preface.")
        document.add_heading("Chapter 1", 1)
        doc = self.read(document)

        self.assertEqual(doc.blocks[0].heading_path, ())


if __name__ == "__main__":
    unittest.main()

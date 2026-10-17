"""Unit tests for :mod:`ai.ingestion.docs_reader` (DOCX).

Runs under both ``pytest`` and ``python -m unittest`` from the project root.
OCR is replaced by a fake; documents are generated with python-docx.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docx import Document as new_docx
from docx.shared import Inches

from ai.ingestion.docs_reader import DocxParseError, DocxReader, read_docx
from ai.ingestion.image_ocr import SKIP_DECODE_FAILED
from ai.ingestion.models import PageType
from tests import pptx_fixtures as fx


class DocxReaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.ocr = fx.FakeOCR()
        self.reader = DocxReader(ocr_processor=self.ocr)  # type: ignore[arg-type]

    def save(self, document, name: str = "doc.docx") -> Path:
        path = self.dir / name
        document.save(str(path))
        return path

    def image_file(self, name: str, color: str = "white") -> str:
        path = self.dir / name
        path.write_bytes(fx.png_bytes(color))
        return str(path)


class StructureTests(DocxReaderTestCase):
    def test_single_logical_page(self) -> None:
        document = new_docx()
        document.add_paragraph("Hello")
        doc = self.reader.read(self.save(document))

        self.assertEqual(len(doc.pages), 1)
        self.assertEqual(doc.pages[0].page_number, 1)
        self.assertEqual(doc.metadata["page_model"], "single_logical_page")

    def test_headings_become_markdown_and_metadata(self) -> None:
        document = new_docx()
        document.add_heading("Title", 0)
        document.add_heading("Chapter", 1)
        document.add_heading("Section", 2)
        document.add_paragraph("Body")
        doc = self.reader.read(self.save(document))

        self.assertIn("# Chapter\n\n## Section", doc.pages[0].text)
        self.assertEqual(
            [(h["level"], h["text"]) for h in doc.metadata["headings"]],
            [(0, "Title"), (1, "Chapter"), (2, "Section")],
        )

    def test_empty_paragraphs_are_skipped(self) -> None:
        document = new_docx()
        document.add_paragraph("one")
        document.add_paragraph("   ")
        document.add_paragraph("two")
        doc = self.reader.read(self.save(document))

        self.assertEqual(doc.statistics["paragraph_count"], 2)

    def test_core_properties_are_in_metadata(self) -> None:
        document = new_docx()
        document.core_properties.title = "Lecture Notes"
        document.core_properties.author = "Dr. Ahmed"
        document.add_paragraph("x")
        doc = self.reader.read(self.save(document))

        self.assertEqual(doc.metadata["title"], "Lecture Notes")
        self.assertEqual(doc.metadata["author"], "Dr. Ahmed")
        self.assertEqual(doc.metadata["file_type"], "docx")


class TableTests(DocxReaderTestCase):
    def test_table_is_extracted_and_rendered_key_value(self) -> None:
        document = new_docx()
        document.add_paragraph("Before")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Name"
        table.cell(0, 1).text = "Value"
        table.cell(1, 0).text = "alpha"
        table.cell(1, 1).text = "1"
        page = self.reader.read(self.save(document)).pages[0]

        self.assertEqual(page.tables[0].rows, [["Name", "Value"], ["alpha", "1"]])
        self.assertIn("[Table 1]\nName: alpha\nValue: 1", page.final_text)
        self.assertEqual(page.page_type, PageType.MIXED_PAGE)

    def test_horizontally_merged_cells_are_collapsed(self) -> None:
        document = new_docx()
        table = document.add_table(rows=2, cols=3)
        table.cell(0, 0).text = "Group"
        table.cell(0, 1).text = "Scores"
        table.cell(0, 1).merge(table.cell(0, 2))
        for col, value in enumerate(["A", "1", "2"]):
            table.cell(1, col).text = value
        rows = self.reader.read(self.save(document)).pages[0].tables[0].rows

        self.assertEqual(rows[0], ["Group", "Scores"])
        self.assertEqual(rows[1], ["A", "1", "2"])

    def test_table_only_document_is_a_table_page(self) -> None:
        document = new_docx()
        table = document.add_table(rows=2, cols=2)
        for r in range(2):
            for c in range(2):
                table.cell(r, c).text = f"r{r}c{c}"
        page = self.reader.read(self.save(document)).pages[0]

        self.assertEqual(page.page_type, PageType.TABLE_PAGE)


class ImageTests(DocxReaderTestCase):
    def test_embedded_image_is_ocred(self) -> None:
        document = new_docx()
        document.add_paragraph("Figure below")
        document.add_picture(self.image_file("a.png"), width=Inches(1))
        doc = self.reader.read(self.save(document))

        page = doc.pages[0]
        self.assertEqual(doc.statistics["image_count"], 1)
        self.assertEqual(doc.statistics["image_ocr_count"], 1)
        self.assertIn("[Embedded Image 1 OCR]\nLOGO TEXT", page.final_text)
        self.assertEqual(page.ocr_text, "LOGO TEXT")

    def test_same_image_part_is_not_duplicated(self) -> None:
        document = new_docx()
        path = self.image_file("a.png")
        document.add_picture(path, width=Inches(1))
        document.add_picture(path, width=Inches(1))  # python-docx reuses the image part
        doc = self.reader.read(self.save(document))

        self.assertEqual(doc.statistics["image_count"], 1)
        self.assertEqual(self.ocr.calls, 1)

    def test_text_only_document_has_full_confidence(self) -> None:
        document = new_docx()
        document.add_paragraph("plain")
        page = self.reader.read(self.save(document)).pages[0]

        self.assertEqual(page.confidence, 1.0)
        self.assertEqual(page.page_type, PageType.TEXT_PAGE)

    def test_undecodable_image_scores_zero_and_warns(self) -> None:
        document = new_docx()
        document.add_picture(self.image_file("a.png"), width=Inches(1))
        path = self.save(document)

        with mock.patch("ai.ingestion.image_ocr.decode_image", side_effect=ValueError("bad")):
            page = self.reader.read(path).pages[0]

        self.assertEqual(page.images[0].ocr_skipped_reason, SKIP_DECODE_FAILED)
        self.assertEqual(page.confidence, 0.0)
        self.assertTrue(any("decode failed" in w for w in page.warnings))


class ErrorHandlingTests(DocxReaderTestCase):
    def test_missing_file(self) -> None:
        with self.assertRaises(DocxParseError):
            self.reader.read(self.dir / "nope.docx")

    def test_wrong_extension_is_rejected_by_default(self) -> None:
        document = new_docx()
        document.add_paragraph("x")
        path = self.save(document, "upload.bin")
        with self.assertRaises(DocxParseError):
            self.reader.read(path)

    def test_suffix_check_can_be_disabled(self) -> None:
        document = new_docx()
        document.add_paragraph("x")
        path = self.save(document, "upload.bin")

        doc = self.reader.read(path, check_suffix=False)
        self.assertEqual(doc.metadata["file_type"], "docx")

    def test_corrupt_file(self) -> None:
        path = self.dir / "broken.docx"
        path.write_bytes(b"not a zip")
        with self.assertRaises(DocxParseError):
            self.reader.read(path)

    def test_convenience_function(self) -> None:
        document = new_docx()
        document.add_paragraph("hi")
        doc = read_docx(self.save(document), ocr_processor=self.ocr)  # type: ignore[arg-type]

        self.assertEqual(doc.statistics["paragraph_count"], 1)


if __name__ == "__main__":
    unittest.main()

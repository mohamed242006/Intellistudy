"""Tests for PPTX / DOCX routing in :class:`IngestionPipeline`.

Usage:
    python -m unittest test_pptx_pipeline            # automated checks
    python test_pptx_pipeline.py "data/uploads/deck.pptx"   # manual dump of one file
"""

from __future__ import annotations

import logging
import sys
import tempfile
import unittest
from pathlib import Path

from docx import Document as new_docx

from ai.ingestion.docs_reader import DocxReader
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.ingestion.models import IngestionError
from ai.ingestion.pptx_reader import PptxParseError, PptxReader
from tests import pptx_fixtures as fx

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class PipelineRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        ocr = fx.FakeOCR()
        self.pipeline = IngestionPipeline(
            pptx_reader=PptxReader(ocr_processor=ocr),  # type: ignore[arg-type]
            docx_reader=DocxReader(ocr_processor=ocr),  # type: ignore[arg-type]
        )

    def _pptx(self, name: str = "lecture.pptx") -> Path:
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "Lecture 1", [("Main", 0), ("Sub", 1)])
        fx.add_chart_slide(prs, "Chart slide")
        return fx.save(prs, self.dir, name)

    def _docx(self, name: str = "notes.docx") -> Path:
        document = new_docx()
        document.add_heading("Notes", level=1)
        document.add_paragraph("Body text")
        path = self.dir / name
        document.save(str(path))
        return path

    def test_pptx_is_routed_to_pptx_reader(self) -> None:
        doc = self.pipeline.ingest(self._pptx())

        self.assertEqual(doc.metadata["file_type"], "pptx")
        self.assertEqual(doc.statistics["slide_count"], 2)
        self.assertIn("[Slide 1]\n# Lecture 1", doc.full_text)
        self.assertIn("[Chart]", doc.full_text)

    def test_docx_is_routed_to_docx_reader(self) -> None:
        doc = self.pipeline.ingest(self._docx())

        self.assertEqual(doc.metadata["file_type"], "docx")
        self.assertIn("Body text", doc.full_text)

    def test_uppercase_extension_and_str_path(self) -> None:
        path = self._pptx("LECTURE.PPTX")
        doc = self.pipeline.ingest(str(path))

        self.assertEqual(doc.metadata["file_type"], "pptx")

    def test_mime_type_overrides_extension_lookup(self) -> None:
        self.assertEqual(self.pipeline.resolve_format("upload.bin", PPTX_MIME), ".pptx")
        self.assertEqual(self.pipeline.resolve_format("upload.bin", DOCX_MIME), ".docx")
        self.assertEqual(
            self.pipeline.resolve_format("x.pdf", "application/pdf; charset=binary"), ".pdf"
        )

    def test_pptx_ingest_with_mime_type(self) -> None:
        doc = self.pipeline.ingest(self._pptx(), mime_type=PPTX_MIME)

        self.assertEqual(doc.metadata["file_type"], "pptx")

    def test_mime_type_works_without_a_usable_extension(self) -> None:
        stored = self.dir / "upload-8f3a.bin"  # how a web upload is often stored
        stored.write_bytes(self._pptx("deck.pptx").read_bytes())
        stored_docx = self.dir / "upload-91bc.tmp"
        stored_docx.write_bytes(self._docx("n.docx").read_bytes())

        pptx_doc = self.pipeline.ingest(stored, mime_type=PPTX_MIME)
        docx_doc = self.pipeline.ingest(stored_docx, mime_type=DOCX_MIME)
        self.assertEqual(pptx_doc.metadata["file_type"], "pptx")
        self.assertEqual(docx_doc.metadata["file_type"], "docx")
        with self.assertRaises(IngestionError):  # no MIME and no extension -> rejected
            self.pipeline.ingest(stored)

    def test_unknown_mime_falls_back_to_extension(self) -> None:
        doc = self.pipeline.ingest(self._pptx(), mime_type="application/octet-stream")

        self.assertEqual(doc.metadata["file_type"], "pptx")

    def test_unsupported_type_is_rejected(self) -> None:
        path = self.dir / "notes.txt"
        path.write_text("hello")
        with self.assertRaises(IngestionError):
            self.pipeline.ingest(path)

    def test_corrupt_pptx_raises_pptx_parse_error(self) -> None:
        path = self.dir / "broken.pptx"
        path.write_bytes(b"not a zip")
        with self.assertRaises(PptxParseError):
            self.pipeline.ingest(path)

    def test_pptx_matches_docx_document_contract(self) -> None:
        pptx_doc = self.pipeline.ingest(self._pptx())
        docx_doc = self.pipeline.ingest(self._docx())

        for doc in (pptx_doc, docx_doc):
            self.assertTrue(doc.source_path)
            self.assertTrue(doc.pages)
            self.assertIn("total_characters", doc.statistics)
            self.assertIn("file_name", doc.metadata)
            self.assertTrue(doc.full_text)
            self.assertIsNotNone(doc.source)


def _manual(path: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(name)s | %(message)s")
    doc = IngestionPipeline().ingest(path)
    print("\n=== STATISTICS ===")
    print(doc.statistics)
    print("\n=== SLIDES ===")
    for slide in doc.metadata.get("slides", []):
        print(slide)
    for page in doc.pages:
        print(f"\n--- page {page.page_number}: {page.page_type.value}, "
              f"confidence={page.confidence}, warnings={page.warnings}")
    print("\n=== FULL TEXT ===")
    print(doc.full_text)


if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        _manual(sys.argv[1])
    else:
        unittest.main()

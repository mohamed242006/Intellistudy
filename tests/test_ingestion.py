"""Ingestion: hostile and unusual files, OCR, tables, determinism and concurrency.

Covers the pipeline, the three readers, the OCR processor, the table extractor, the
document builder and the shared helper modules with inputs a production upload will meet.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import pymupdf as fitz
from docx import Document as new_docx
from PIL import Image, ImageDraw, ImageFont

from ai.ingestion import image_ocr, structure
from ai.ingestion.cleaners import clean_text, is_heading, mark_headings
from ai.ingestion.docs_reader import DocxParseError
from ai.ingestion.document_builder import ConfidenceScorer, PageClassifier
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.ingestion.models import (
    Document,
    ImageData,
    IngestionError,
    OCRError,
    PageContent,
    PageType,
    PDFParseError,
    TableData,
    TableExtractionError,
)
from ai.ingestion.ocr_processor import OCRProcessor
from ai.ingestion.pptx_reader import PptxParseError
from ai.ingestion.table_extractor import TableExtractor
from tests import pdf_fixtures as pf
from tests import pptx_fixtures as fx

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "uploads"
ARIAL = Path("C:/Windows/Fonts/arial.ttf")
TESSERACT = OCRProcessor().available


class TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.ocr = fx.FakeOCR()
        from ai.ingestion.docs_reader import DocxReader
        from ai.ingestion.pptx_reader import PptxReader

        self.pipeline = IngestionPipeline(
            docx_reader=DocxReader(ocr_processor=self.ocr),  # type: ignore[arg-type]
            pptx_reader=PptxReader(ocr_processor=self.ocr),  # type: ignore[arg-type]
        )

    def pdf(self, name="a.pdf", pages=None, **kw) -> Path:
        return pf.make_pdf(self.dir / name, pages or [pf.body(), pf.body()], **kw)

    def docx(self, name="a.docx", text="Body text of the document.") -> Path:
        document = new_docx()
        document.add_heading("Title", 1)
        document.add_paragraph(text)
        path = self.dir / name
        document.save(str(path))
        return path

    def pptx(self, name="a.pptx") -> Path:
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "Lecture", [("Main point of the lecture", 0)])
        return fx.save(prs, self.dir, name)


# --------------------------------------------------------------------------- hostile files
class HostileFileTests(TempDirCase):
    def test_empty_files_of_every_type_raise_the_typed_error(self) -> None:
        for name, error in (("e.pdf", PDFParseError), ("e.docx", DocxParseError), ("e.pptx", PptxParseError)):
            with self.subTest(name=name):
                (self.dir / name).write_bytes(b"")
                with self.assertRaises(error):
                    self.pipeline.ingest(self.dir / name)

    def test_every_parse_error_is_an_ingestion_error(self) -> None:
        for error in (PDFParseError, DocxParseError, PptxParseError):
            self.assertTrue(issubclass(error, IngestionError))

    def test_truncated_and_garbage_pdfs(self) -> None:
        data = self.pdf().read_bytes()
        (self.dir / "trunc.pdf").write_bytes(data[: len(data) // 2])
        (self.dir / "garbage.pdf").write_bytes(os.urandom(4096))
        (self.dir / "text.pdf").write_text("this is not a pdf")
        for name in ("trunc.pdf", "garbage.pdf", "text.pdf"):
            with self.subTest(name=name), self.assertRaises(PDFParseError):
                self.pipeline.ingest(self.dir / name)

    def test_password_protected_pdf_is_rejected_with_a_clear_reason(self) -> None:
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "secret")
        doc.save(str(self.dir / "enc.pdf"), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
        doc.close()

        with self.assertRaisesRegex(PDFParseError, "password"):
            self.pipeline.ingest(self.dir / "enc.pdf")

    def test_encrypted_office_files_and_non_office_zips(self) -> None:
        ole = bytes.fromhex("D0CF11E0A1B11AE1") + os.urandom(2000)  # how Word/PowerPoint store passwords
        (self.dir / "enc.docx").write_bytes(ole)
        (self.dir / "enc.pptx").write_bytes(ole)
        with zipfile.ZipFile(self.dir / "plain.docx", "w") as z:
            z.writestr("hello.txt", "x")
        with self.assertRaises(DocxParseError):
            self.pipeline.ingest(self.dir / "enc.docx")
        with self.assertRaises(PptxParseError):
            self.pipeline.ingest(self.dir / "enc.pptx")
        with self.assertRaises(DocxParseError):
            self.pipeline.ingest(self.dir / "plain.docx")

    def test_office_file_with_corrupt_main_part(self) -> None:
        source = self.docx()
        broken = self.dir / "broken.docx"
        with zipfile.ZipFile(source) as zin, zipfile.ZipFile(broken, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    data = b"<not-xml"
                zout.writestr(item, data)

        with self.assertRaises(DocxParseError):
            self.pipeline.ingest(broken)

    def test_wrong_extension_missing_file_and_directories(self) -> None:
        (self.dir / "notes.txt").write_text("x")
        with self.assertRaises(IngestionError):
            self.pipeline.ingest(self.dir / "notes.txt")
        with self.assertRaises(IngestionError):
            self.pipeline.ingest(self.dir / "no-extension")
        with self.assertRaises(PDFParseError):
            self.pipeline.ingest(self.dir / "missing.pdf")
        with self.assertRaises(IngestionError):
            self.pipeline.ingest(self.dir)

    def test_a_docx_uploaded_with_a_pptx_mime_type_fails_cleanly(self) -> None:
        mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        with self.assertRaises(PptxParseError):
            self.pipeline.ingest(self.docx(), mime_type=mime)

    def test_extension_case_and_unicode_file_names(self) -> None:
        upper = self.dir / "LECTURE.PDF"
        upper.write_bytes(self.pdf().read_bytes())
        odd = self.dir / "محاضرة ünï 文档 (1).pdf"
        odd.write_bytes(self.pdf().read_bytes())

        self.assertEqual(self.pipeline.ingest(upper).source.file_type, "pdf")
        self.assertEqual(self.pipeline.ingest(odd).source.file_name, odd.name)

    def test_pptx_without_slides_and_blank_pdf_page(self) -> None:
        empty = fx.save(fx.blank_presentation(), self.dir, "none.pptx")
        doc = self.pipeline.ingest(empty)
        self.assertEqual((len(doc.pages), doc.full_text, doc.statistics["page_count"]), (0, "", 0))

        blank = fitz.open()
        blank.new_page()
        blank.save(str(self.dir / "blank.pdf"))
        blank.close()
        doc = self.pipeline.ingest(self.dir / "blank.pdf")
        self.assertEqual(len(doc.pages), 1)
        self.assertEqual(doc.blocks, [])
        self.assertIn(1, doc.statistics["low_confidence_pages"])  # an empty page is flagged


# --------------------------------------------------------------------------- scanned / language
class ScannedAndLanguageTests(TempDirCase):
    def scanned_pdf(self, lines: list[str]) -> Path:
        image = Image.new("RGB", (1700, 140 + 130 * len(lines)), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(str(ARIAL), 46)
        for i, line in enumerate(lines):
            draw.text((60, 70 + i * 130), line, fill="black", font=font)
        image.save(self.dir / "scan.png")
        doc = fitz.open()
        page = doc.new_page()
        page.insert_image(page.rect, filename=str(self.dir / "scan.png"))
        doc.save(str(self.dir / "scan.pdf"))
        doc.close()
        return self.dir / "scan.pdf"

    @unittest.skipUnless(TESSERACT and ARIAL.exists(), "needs Tesseract and Arial")
    def test_scanned_page_is_ocred_and_classified(self) -> None:
        path = self.scanned_pdf(["Process scheduling in operating systems",
                                 "The scheduler selects the next process from the ready queue"])
        doc = IngestionPipeline().ingest(path)
        page = doc.pages[0]

        self.assertEqual(page.page_type, PageType.SCANNED_PAGE)
        self.assertTrue(page.ocr_applied)
        self.assertGreater(page.confidence, 0.8)
        self.assertIn("scheduler", page.final_text.lower())
        self.assertEqual(doc.statistics["ocr_pages"], 1)

    @unittest.skipUnless(TESSERACT and ARIAL.exists(), "needs Tesseract and Arial")
    def test_scanned_page_flows_through_chunking(self) -> None:
        from ai.chunking import ChunkContext, ChunkingEngine

        doc = IngestionPipeline().ingest(self.scanned_pdf(["Memory management uses paging and segmentation"]))
        chunks = ChunkingEngine(strict=True).chunk(doc, ChunkContext("u", "c", "d"))

        self.assertTrue(chunks)
        self.assertEqual(chunks[0].source_kind, "ocr_page")
        self.assertIsNotNone(chunks[0].ocr_confidence)

    def test_ocr_disabled_leaves_a_scanned_page_empty_but_valid(self) -> None:
        if not ARIAL.exists():
            self.skipTest("needs Arial")
        path = self.scanned_pdf(["Some scanned words appear here"])
        doc = IngestionPipeline(enable_ocr=False, enable_image_ocr=False).ingest(path)

        self.assertEqual(doc.blocks, [])
        self.assertEqual(doc.pages[0].confidence, 0.0)

    @unittest.skipUnless(ARIAL.exists(), "needs Arial")
    def test_mixed_english_and_arabic_does_not_crash_and_keeps_english(self) -> None:
        def draw(page, _n):
            page.insert_text((72, 100), "Operating systems overview", fontsize=14)
            page.insert_text((72, 140), "مرحبا بالعالم نص عربي للاختبار", fontsize=14,
                             fontfile=str(ARIAL), fontname="arial")
            page.insert_text((72, 180), "Back to English text after the Arabic line", fontsize=14)

        doc = IngestionPipeline().ingest(pf.make_custom_pdf(self.dir / "ar.pdf", draw))
        text = doc.full_text

        self.assertIn("Operating systems overview", text)
        self.assertIn("Back to English text", text)
        self.assertTrue(any("\u0600" <= ch <= "\u06ff" for ch in text))  # Arabic characters survive

    @unittest.expectedFailure
    @unittest.skipUnless(ARIAL.exists(), "needs Arial")
    def test_KNOWN_LIMITATION_arabic_text_keeps_logical_order(self) -> None:
        # PyMuPDF returns right-to-left runs in visual order, so Arabic comes out reversed.
        def draw(page, _n):
            page.insert_text((72, 100), "مرحبا بالعالم", fontsize=14, fontfile=str(ARIAL), fontname="arial")

        text = IngestionPipeline().ingest(pf.make_custom_pdf(self.dir / "ar2.pdf", draw)).full_text
        self.assertIn("مرحبا", text)


# --------------------------------------------------------------------------- duplicates / huge
class DuplicateAndSizeTests(TempDirCase):
    def test_identical_bytes_give_identical_identity(self) -> None:
        one = self.pdf("one.pdf")
        two = self.dir / "copy-of-one.pdf"
        two.write_bytes(one.read_bytes())
        a, b = self.pipeline.ingest(one), self.pipeline.ingest(two)

        self.assertEqual((a.source.sha256, a.source.doc_id), (b.source.sha256, b.source.doc_id))
        self.assertEqual([p.final_text for p in a.pages], [p.final_text for p in b.pages])
        self.assertNotEqual(a.source.file_name, b.source.file_name)

    def test_any_change_changes_the_hash(self) -> None:
        a = self.pipeline.ingest(self.docx("a.docx", "Body text of the document."))
        b = self.pipeline.ingest(self.docx("b.docx", "Body text of the document!"))

        self.assertNotEqual(a.source.sha256, b.source.sha256)
        self.assertNotEqual(a.source.doc_id, b.source.doc_id)

    def test_large_pdf_keeps_page_order_and_numbers(self) -> None:
        pages = [[(f"Chapter {n}", 20.0), *pf.body(f"Unique marker number {n} on this page.")] for n in range(1, 121)]
        doc = IngestionPipeline().ingest(pf.make_pdf(self.dir / "big.pdf", pages, start_y=200.0))

        self.assertEqual(len(doc.pages), 120)
        self.assertEqual([p.page_number for p in doc.pages], list(range(1, 121)))
        for n in (1, 60, 120):
            self.assertIn(f"Unique marker number {n} on this page.", doc.pages[n - 1].final_text)
        orders = [b.order for b in doc.blocks]
        self.assertEqual(orders, list(range(len(orders))))

    def test_large_docx_and_pptx(self) -> None:
        document = new_docx()
        for i in range(3000):
            document.add_paragraph(f"Paragraph number {i} with some filler words in it.")
        path = self.dir / "big.docx"
        document.save(str(path))
        doc = self.pipeline.ingest(path)
        self.assertEqual(doc.statistics["paragraph_count"], 3000)
        self.assertIn("Paragraph number 2999", doc.full_text)

        prs = fx.blank_presentation()
        for i in range(150):
            fx.add_bullet_slide(prs, f"Slide {i}", [(f"Point {i}", 0)])
        deck = self.pipeline.ingest(fx.save(prs, self.dir, "big.pptx"))
        self.assertEqual(deck.statistics["page_count"], 150)
        self.assertEqual(deck.metadata["slides"][149]["title"], "Slide 149")


# --------------------------------------------------------------------------- determinism / concurrency
class DeterminismTests(TempDirCase):
    SCRIPT = """
import json, sys
sys.path.insert(0, sys.argv[1])
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.chunking import ChunkingEngine, ChunkContext
from tests.chunk_fixtures import WordCounter
out = {}
pipeline = IngestionPipeline()
for path in sys.argv[2:]:
    doc = pipeline.ingest(path)
    cs = ChunkingEngine(tokenizer=WordCounter()).run(doc, ChunkContext("u", "c", "uid", "m"))
    out[path] = {"doc_id": doc.source.doc_id, "text": doc.full_text,
                 "children": [c.chunk_id for c in cs.children],
                 "parents": [p.chunk_id for p in cs.parents],
                 "embed": [c.embedding_hash for c in cs.children]}
print(json.dumps(out))
"""

    def run_with_hash_seed(self, seed: str, files: list[Path]) -> dict:
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONUTF8": "1"}
        done = subprocess.run([sys.executable, "-c", self.SCRIPT, str(ROOT), *map(str, files)],
                              capture_output=True, text=True, env=env, cwd=ROOT, timeout=240)
        self.assertEqual(done.returncode, 0, done.stderr[-1500:])
        return json.loads(done.stdout.strip().splitlines()[-1])

    def test_ids_and_hashes_do_not_depend_on_python_hash_randomisation(self) -> None:
        files = [
            self.pdf("d.pdf", pages=[[("Heading", 20.0), *pf.body()], pf.body("second page text here")]),
            self.docx("d.docx"),
            self.pptx("d.pptx"),
        ]
        first = self.run_with_hash_seed("1", files)
        second = self.run_with_hash_seed("2", files)
        third = self.run_with_hash_seed("random", files)

        self.assertEqual(first, second)
        self.assertEqual(first, third)
        self.assertTrue(all(v["children"] for v in first.values()))

    def test_repeated_ingestion_in_one_process_is_identical(self) -> None:
        path = self.pdf("r.pdf", pages=[[("Heading", 20.0), *pf.body()]])
        a, b = self.pipeline.ingest(path), self.pipeline.ingest(path)

        self.assertEqual([x.final_text for x in a.pages], [x.final_text for x in b.pages])
        self.assertEqual([x.to_dict() for x in a.blocks], [x.to_dict() for x in b.blocks])


@unittest.skipUnless((SAMPLES / "test2.pdf").exists() and (SAMPLES / "test.pdf").exists(), "sample PDFs missing")
class ConcurrencyTests(unittest.TestCase):
    """REG-04: a shared pipeline used to corrupt text and tables under concurrent calls."""

    def test_concurrent_pdf_ingestion_on_one_pipeline_matches_sequential(self) -> None:
        paths = [SAMPLES / "test2.pdf", SAMPLES / "test.pdf"]  # one table, one image/OCR page
        expected = {p: IngestionPipeline().ingest(p) for p in paths}
        shared = IngestionPipeline()
        results: dict[tuple[int, Path], Document | Exception] = {}

        def work(i: int, path: Path) -> None:
            try:
                results[(i, path)] = shared.ingest(path)
            except Exception as exc:
                results[(i, path)] = exc

        threads = [threading.Thread(target=work, args=(i, p)) for i in range(4) for p in paths]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for (i, path), got in results.items():
            with self.subTest(thread=i, file=path.name):
                self.assertNotIsInstance(got, Exception, got)
                assert isinstance(got, Document)
                want = expected[path]
                self.assertEqual([p.final_text for p in got.pages], [p.final_text for p in want.pages])
                self.assertEqual([len(p.tables) for p in got.pages], [len(p.tables) for p in want.pages])
                self.assertEqual(sum(len(p.warnings) for p in got.pages), 0)


# --------------------------------------------------------------------------- OCR processor
class OcrProcessorTests(unittest.TestCase):
    def processor(self, **kw) -> OCRProcessor:
        with mock.patch("ai.ingestion.ocr_processor.pytesseract.get_tesseract_version", return_value="5.0"):
            return OCRProcessor(**kw)

    @staticmethod
    def tess(words, confs=None, pars=None):
        n = len(words)
        return {
            "text": list(words),
            "conf": confs if confs is not None else [90.0] * n,
            "block_num": [1] * n,
            "par_num": pars if pars is not None else [1] * n,
            "line_num": [1] * n,
        }

    def image(self, size=(400, 300)):
        return Image.new("RGB", size, "white")

    def test_engine_missing_is_reported_not_silently_ignored(self) -> None:
        with mock.patch("ai.ingestion.ocr_processor.pytesseract.get_tesseract_version", side_effect=OSError):
            proc = OCRProcessor()
        self.assertFalse(proc.available)
        with self.assertRaises(OCRError):
            proc.process_image(self.image())

    def test_tiny_thin_and_text_free_images_are_skipped_with_reasons(self) -> None:
        proc = self.processor()
        self.assertEqual(proc.process_image(self.image((20, 20))).skipped_reason, "too_small")
        self.assertEqual(proc.process_image(self.image((5000, 120))).skipped_reason, "too_thin")
        with mock.patch("ai.ingestion.ocr_processor.pytesseract.image_to_data", return_value=self.tess(["a"])):
            self.assertEqual(proc.process_image(self.image()).skipped_reason, "no_text")
        words = ["blurry", "unreliable", "recognition", "output"]
        with mock.patch("ai.ingestion.ocr_processor.pytesseract.image_to_data",
                        return_value=self.tess(words, confs=[40.0] * 4)):
            result = proc.process_image(self.image())
        self.assertEqual((result.skipped_reason, result.text), ("low_confidence", ""))

    def test_good_text_is_returned_with_mean_confidence_and_paragraphs(self) -> None:
        words = ["Hello", "world", "second", "paragraph", "here"]
        data = self.tess(words, confs=[90.0, 80.0, 70.0, 100.0, 60.0], pars=[1, 1, 2, 2, 2])
        with mock.patch("ai.ingestion.ocr_processor.pytesseract.image_to_data", return_value=data):
            result = self.processor().process_image(self.image())

        self.assertEqual(result.text, "Hello world\n\nsecond paragraph here")
        self.assertAlmostEqual(result.confidence, 80.0)
        self.assertTrue(result.applied)

    def test_low_confidence_words_are_dropped_but_still_count_towards_the_mean(self) -> None:
        data = self.tess(["good", "words", "noise", "again", "fine"], confs=[95.0, 95.0, 10.0, 95.0, 95.0])
        with mock.patch("ai.ingestion.ocr_processor.pytesseract.image_to_data", return_value=data):
            result = self.processor(min_image_confidence=50.0).process_image(self.image())

        self.assertNotIn("noise", result.text)
        self.assertLess(result.confidence, 95.0)

    def test_engine_failure_becomes_an_ocr_error(self) -> None:
        with mock.patch("ai.ingestion.ocr_processor.pytesseract.image_to_data", side_effect=RuntimeError("boom")):
            with self.assertRaises(OCRError):
                self.processor().process_image(self.image())

    def test_cache_key_avoids_a_second_run_and_clear_cache_resets_it(self) -> None:
        proc = self.processor()
        data = self.tess(["cached", "result", "words", "here", "now"])
        with mock.patch("ai.ingestion.ocr_processor.pytesseract.image_to_data", return_value=data) as engine:
            first = proc.process_image(self.image(), cache_key="k")
            second = proc.process_image(self.image(), cache_key="k")
            proc.process_image(self.image(), cache_key=None)
            self.assertEqual(engine.call_count, 2)  # key hit skipped one run; None is never cached
            proc.clear_cache()
            proc.process_image(self.image(), cache_key="k")
            self.assertEqual(engine.call_count, 3)
        self.assertEqual(first, second)

    def test_non_numeric_confidences_are_ignored(self) -> None:
        data = self.tess(["valid", "words", "in", "this", "line"], confs=["90", "n/a", None, 85, -1])
        with mock.patch("ai.ingestion.ocr_processor.pytesseract.image_to_data", return_value=data):
            result = self.processor().process_image(self.image())

        self.assertIn("valid", result.text)

    def test_prepare_image_rescales_small_and_huge_images(self) -> None:
        proc = self.processor()
        small = proc._prepare_image(self.image((100, 100)))
        huge = proc._prepare_image(self.image((6000, 2000)))

        self.assertGreater(max(small.size), 100)
        self.assertLessEqual(max(huge.size), proc.max_ocr_side)


# --------------------------------------------------------------------------- tables
@unittest.skipUnless((SAMPLES / "Intellistudy_final_proposal.pdf").exists(), "sample PDF missing")
class TableExtractorTests(unittest.TestCase):
    PATH = SAMPLES / "Intellistudy_final_proposal.pdf"

    def test_extracts_rectangular_tables_with_positions(self) -> None:
        with TableExtractor().open(self.PATH) as extractor:
            found = [t for page in range(1, 11) for t in extractor.extract(page)]

        self.assertGreaterEqual(len(found), 3)
        for table in found:
            width = {len(r) for r in table.rows}
            self.assertEqual(len(width), 1)  # padded to a rectangle
            self.assertIsNotNone(table.bbox)
            self.assertGreaterEqual(table.n_rows, 2)

    def test_usage_errors(self) -> None:
        extractor = TableExtractor()
        with self.assertRaises(TableExtractionError):
            extractor.extract(1)  # not opened
        with self.assertRaises(TableExtractionError):
            TableExtractor().open("does-not-exist.pdf")
        extractor.open(self.PATH)
        with self.assertRaises(TableExtractionError):
            extractor.extract(9999)
        extractor.close()
        extractor.close()  # idempotent

    def test_size_filters(self) -> None:
        with TableExtractor(min_rows=50).open(self.PATH) as strict:
            self.assertEqual([t for p in range(1, 7) for t in strict.extract(p)], [])


# --------------------------------------------------------------------------- helper modules
class ImageOcrHelperTests(unittest.TestCase):
    @staticmethod
    def png(mode: str, **kw) -> bytes:
        buf = io.BytesIO()
        Image.new(mode, (60, 40), kw.get("color")).save(buf, kw.get("format", "PNG"))
        return buf.getvalue()

    def test_decode_handles_every_colour_mode(self) -> None:
        cases = {
            "RGB": self.png("RGB", color=(10, 20, 30)),
            "RGBA": self.png("RGBA", color=(10, 20, 30, 0)),
            "L": self.png("L", color=128),
            "LA": self.png("LA", color=(128, 255)),
            "P": self.png("P", color=3),
            "CMYK": self.png("CMYK", color=(0, 0, 0, 0), format="JPEG"),
            "I;16": self.png("I;16", color=1000),
        }
        for mode, blob in cases.items():
            with self.subTest(mode=mode):
                self.assertIn(image_ocr.decode_image(blob).mode, ("RGB", "L"))

    def test_transparent_pixels_are_composited_on_white(self) -> None:
        pixel = image_ocr.decode_image(self.png("RGBA", color=(0, 0, 0, 0))).getpixel((5, 5))

        self.assertEqual(pixel, (255, 255, 255))

    def test_undecodable_bytes_are_reported_not_raised(self) -> None:
        data = ImageData(page_number=1, index=0, xref=0, width=0, height=0)
        detail = image_ocr.ocr_image_blob(mock.Mock(), b"not an image", data, "label")

        self.assertIn("decode failed", detail or "")
        self.assertEqual(data.ocr_skipped_reason, image_ocr.SKIP_DECODE_FAILED)

    def test_vector_formats_are_a_mild_skip(self) -> None:
        data = ImageData(page_number=1, index=0, xref=0, width=0, height=0)
        detail = image_ocr.ocr_image_blob(mock.Mock(), b"EMF", data, "l", is_unsupported=lambda: True)

        self.assertEqual(data.ocr_skipped_reason, image_ocr.SKIP_UNSUPPORTED_FORMAT)
        self.assertEqual(detail, image_ocr.UNSUPPORTED_FORMAT_WARNING)

    def test_scoring_ranges(self) -> None:
        def image(**kw):
            return ImageData(page_number=1, index=0, xref=0, width=1, height=1, **kw)

        self.assertEqual(image_ocr.score_image(image(ocr_skipped_reason="decode_failed")), 0.0)
        self.assertEqual(image_ocr.score_image(image(ocr_applied=True, ocr_text="x", ocr_confidence=100.0)), 1.0)
        self.assertEqual(image_ocr.score_image(image(ocr_applied=True, ocr_text="x", ocr_confidence=0.0)), 0.85)
        self.assertEqual(image_ocr.score_image(image(ocr_applied=True)), 0.80)
        self.assertEqual(image_ocr.score_image(image(ocr_skipped_reason="weird")), 0.75)
        self.assertEqual(image_ocr.score_image(image()), 0.75)
        self.assertEqual(image_ocr.compute_confidence([]), 1.0)
        self.assertEqual(image_ocr.compute_confidence([], [0.5, 1.0]), 0.75)
        self.assertEqual(image_ocr.mean_ocr_confidence([]), None)


class DocumentBuilderTests(unittest.TestCase):
    def test_page_classifier_branches(self) -> None:
        classify = PageClassifier(min_text_chars=50).classify
        long_text = "x" * 200
        table = TableData(page_number=1, index=0, rows=[["a", "b"], ["1", "2"]])
        image = ImageData(page_number=1, index=0, xref=1, width=1, height=1, ocr_text="words", ocr_applied=True)

        self.assertEqual(classify(PageContent(page_number=1, text=long_text)), PageType.TEXT_PAGE)
        self.assertEqual(classify(PageContent(page_number=1, ocr_applied=True, ocr_text="t")), PageType.SCANNED_PAGE)
        self.assertEqual(classify(PageContent(page_number=1, ocr_applied=True, text=long_text)), PageType.MIXED_PAGE)
        self.assertEqual(classify(PageContent(page_number=1, tables=[table])), PageType.TABLE_PAGE)
        self.assertEqual(classify(PageContent(page_number=1, tables=[table], text=long_text)), PageType.MIXED_PAGE)
        self.assertEqual(classify(PageContent(page_number=1, images=[image])), PageType.SCANNED_PAGE)
        self.assertEqual(classify(PageContent(page_number=1, images=[image], text=long_text)), PageType.MIXED_PAGE)

    def test_confidence_scorer_branches(self) -> None:
        score = ConfidenceScorer.score
        self.assertEqual(score(PageContent(page_number=1)), 0.0)
        self.assertEqual(score(PageContent(page_number=1, ocr_applied=True, ocr_text="t", ocr_confidence=88.0)), 0.88)
        self.assertEqual(score(PageContent(page_number=1, ocr_applied=True)), 0.0)
        self.assertEqual(score(PageContent(page_number=1, tables=[TableData(1, 0, [["a"], ["b"]])])), 0.9)
        clean = score(PageContent(page_number=1, text="Plain readable text " * 5))
        garbled = score(PageContent(page_number=1, text="\ufffd\x01\x02 " * 40))
        self.assertGreater(clean, 0.9)
        self.assertLess(garbled, clean)

    def test_blend_of_native_text_and_image_ocr(self) -> None:
        image = ImageData(page_number=1, index=0, xref=1, width=1, height=1,
                          ocr_text="y" * 100, ocr_applied=True, ocr_confidence=50.0)
        page = PageContent(page_number=1, text="Plain readable text " * 5, images=[image])

        self.assertLess(ConfidenceScorer.score(page), ConfidenceScorer.score(PageContent(page_number=1, text=page.text)))


class CleanersAndStructureTests(unittest.TestCase):
    def test_invisible_characters_are_removed_but_joiners_kept(self) -> None:
        self.assertEqual(clean_text("a\u200bb\u2060c\ufeffd"), "abcd")
        self.assertEqual(clean_text("a\u200db\u200cc"), "a\u200db\u200cc")  # shaping characters stay

    def test_heading_heuristics(self) -> None:
        self.assertTrue(is_heading("1.2 Process Scheduling"))
        self.assertTrue(is_heading("INTRODUCTION"))
        self.assertFalse(is_heading("this is a normal sentence that ends with a full stop."))
        self.assertFalse(is_heading(""))
        self.assertFalse(is_heading("x" * 200))
        marked = mark_headings("Intro text.\n\nBackground\n\nBody text continues here.")
        self.assertIn("## Background", marked)

    def test_pdf_dates(self) -> None:
        self.assertEqual(structure.pdf_date_to_iso("D:20240131120000+02'00'"), "2024-01-31T12:00:00")
        self.assertEqual(structure.pdf_date_to_iso("D:2024"), "2024-01-01T00:00:00")
        for bad in (None, 5, "", "garbage", "D:20241345"):
            self.assertIsNone(structure.pdf_date_to_iso(bad))

    def test_list_numbering_schemes(self) -> None:
        f = structure.format_number
        self.assertEqual([f(n, "alphaLcPeriod") for n in (1, 26, 27, 52, 53)], ["a.", "z.", "aa.", "az.", "ba."])
        self.assertEqual([f(n, "romanLcPeriod") for n in (1, 4, 9, 14, 40, 90, 400, 1994)],
                         ["i.", "iv.", "ix.", "xiv.", "xl.", "xc.", "cd.", "mcmxciv."])
        self.assertEqual(f(7, "arabicParenBoth"), "(7)")
        self.assertEqual(f(7, "arabicParenR"), "7)")
        self.assertEqual(f(7, "arabicPlain"), "7")
        self.assertEqual(f(3, "alphaUcPeriod"), "C.")
        self.assertEqual(f(3, "unknownScheme"), "3.")

    def test_citation_labels(self) -> None:
        block = structure.Block(structure.BlockType.PARAGRAPH, "x", 3, heading_path=("A", "B"))
        self.assertEqual(structure.citation_label(block, "page"), "p. 3 > A > B")
        self.assertEqual(structure.citation_label(block, "slide"), "slide 3 > A > B")
        self.assertEqual(structure.citation_label(block, "document"), "A > B")


if __name__ == "__main__":
    unittest.main()

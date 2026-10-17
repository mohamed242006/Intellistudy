"""Unit tests for :mod:`ai.ingestion.pptx_reader`.

Runs under both ``pytest`` and ``python -m unittest`` from the project root.
Decks are generated on the fly with python-pptx; OCR is replaced by a fake.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pptx.util import Inches

from ai.ingestion.image_ocr import (
    SKIP_DECODE_FAILED,
    SKIP_UNSUPPORTED_FORMAT,
    compute_confidence,
    score_image,
)
from ai.ingestion.models import ImageData, PageType
from ai.ingestion.pptx_reader import (
    PptxParseError,
    PptxReader,
    _RawImage,
    read_pptx,
)
from tests import pptx_fixtures as fx


class PptxReaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.ocr = fx.FakeOCR()
        self.reader = PptxReader(ocr_processor=self.ocr)  # type: ignore[arg-type]

    def read(self, prs, name: str = "deck.pptx"):
        return self.reader.read(fx.save(prs, self.dir, name))


class TextAndStructureTests(PptxReaderTestCase):
    def test_slide_number_footer_and_date_placeholders_are_not_content(self) -> None:
        # Regression (real deck): "6" from the slide-number placeholder became a chunk.
        from copy import deepcopy

        prs = fx.blank_presentation()
        slide = fx.add_bullet_slide(prs, "Ciphers", [("Caesar shifts letters", 0)])
        for layout_shape in slide.slide_layout.placeholders:
            if layout_shape.placeholder_format.type in (13, 15, 16):  # SLIDE_NUMBER, FOOTER, DATE
                element = deepcopy(layout_shape._element)
                slide.shapes._spTree.append(element)
        for shape in slide.shapes:
            if shape.is_placeholder and shape.placeholder_format.type in (13, 15, 16):
                shape.text_frame.text = "6"
        self.assertGreaterEqual(
            sum(1 for sh in slide.shapes if sh.is_placeholder and sh.placeholder_format.type in (13, 15, 16)), 1
        )
        page = self.read(prs).pages[0]

        self.assertNotIn("6", [b.text for b in page.blocks])
        self.assertIn("Caesar shifts letters", page.text)

    def test_title_appears_exactly_once(self) -> None:
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "Intro to AOP", [("Point", 0)])
        page = self.read(prs).pages[0]

        self.assertEqual(page.text.count("Intro to AOP"), 1)
        self.assertEqual(page.final_text.count("Intro to AOP"), 1)
        self.assertTrue(page.text.startswith("# Intro to AOP"))

    def test_nested_bullets_keep_structure(self) -> None:
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "T", [("Main Topic", 0), ("Sub Topic", 1), ("Detail", 2)])
        page = self.read(prs).pages[0]

        self.assertIn("- Main Topic\n  - Sub Topic\n    - Detail", page.text)
        self.assertIn("  - Sub Topic", page.final_text)  # nesting survives final cleaning

    def test_numbered_list_keeps_numbers(self) -> None:
        prs = fx.blank_presentation()
        slide = fx.add_bullet_slide(
            prs, "T", [("Introduction", 0), ("Methods", 0), ("Results", 0)]
        )
        for paragraph in slide.placeholders[1].text_frame.paragraphs:
            fx.make_numbered(paragraph)
        page = self.read(prs).pages[0]

        self.assertIn("1. Introduction\n2. Methods\n3. Results", page.text)

    def test_plain_textbox_is_not_bulleted(self) -> None:
        prs = fx.blank_presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[fx.LAYOUT_BLANK])
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
        box.text_frame.text = "Just a sentence"
        page = self.read(prs).pages[0]

        self.assertEqual(page.text, "Just a sentence")

    def test_side_by_side_boxes_read_left_to_right(self) -> None:
        prs = fx.blank_presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[fx.LAYOUT_BLANK])
        right = slide.shapes.add_textbox(Inches(5), Inches(1.00), Inches(3), Inches(1))
        right.text_frame.text = "RIGHT"
        left = slide.shapes.add_textbox(Inches(0.5), Inches(1.02), Inches(3), Inches(1))
        left.text_frame.text = "LEFT"  # a hair lower, but same visual row
        page = self.read(prs).pages[0]

        self.assertLess(page.text.index("LEFT"), page.text.index("RIGHT"))

    def test_speaker_notes_are_included(self) -> None:
        prs = fx.blank_presentation()
        slide = fx.add_bullet_slide(prs, "T", [("Point", 0)])
        slide.notes_slide.notes_text_frame.text = "Remember the demo"
        doc = self.read(prs)

        self.assertIn("[Speaker Notes]\nRemember the demo", doc.pages[0].final_text)
        self.assertTrue(doc.metadata["slides"][0]["has_notes"])

    def test_single_page_marker_only(self) -> None:
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "One", [("a", 0)])
        doc = self.read(prs)

        self.assertNotIn("[Slide", doc.pages[0].final_text)
        self.assertTrue(doc.full_text.startswith("[Slide 1]\n# One"))
        self.assertNotIn("[Page", doc.full_text)

    def test_empty_slide_has_no_final_text(self) -> None:
        prs = fx.blank_presentation()
        prs.slides.add_slide(prs.slide_layouts[fx.LAYOUT_BLANK])
        page = self.read(prs).pages[0]

        self.assertEqual(page.final_text, "")
        self.assertEqual(page.confidence, 1.0)


class TitleDetectionTests(PptxReaderTestCase):
    def test_title_inside_group_is_found(self) -> None:
        prs = fx.blank_presentation()
        fx.add_grouped_title_slide(prs, "Grouped Title")
        doc = self.read(prs)

        grouped = doc.get_page(2)
        assert grouped is not None
        self.assertEqual(doc.metadata["slides"][1]["title"], "Grouped Title")
        self.assertEqual(grouped.text.count("Grouped Title"), 1)
        self.assertIn("Grouped body", grouped.text)


class HiddenSlideTests(PptxReaderTestCase):
    def test_hidden_slide_is_kept_and_flagged(self) -> None:
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "Visible", [("a", 0)])
        hidden = fx.add_bullet_slide(prs, "Hidden", [("b", 0)])
        hidden._element.set("show", "0")
        doc = self.read(prs)

        self.assertEqual(len(doc.pages), 2)
        self.assertEqual([s["hidden"] for s in doc.metadata["slides"]], [False, True])
        self.assertEqual(doc.statistics["hidden_slide_count"], 1)
        self.assertIn("Hidden", doc.pages[1].text)  # content is preserved


class ChartTests(PptxReaderTestCase):
    def test_chart_content_is_extracted(self) -> None:
        prs = fx.blank_presentation()
        fx.add_chart_slide(prs)
        page = self.read(prs).pages[0]

        self.assertIn("[Chart]", page.text)
        self.assertIn("Title: Student Performance", page.text)
        self.assertIn("X-Axis: Exam 1, Exam 2, Final", page.text)
        self.assertIn("Y-Axis: Score", page.text)
        self.assertIn("Series: Class A, Class B", page.text)
        self.assertIn("Legend: Class A, Class B", page.text)
        self.assertIn("Chart Type: Column Clustered Chart", page.text)
        self.assertEqual(page.confidence, 1.0)
        self.assertEqual(page.warnings, [])

    def test_unreadable_chart_warns_and_lowers_confidence(self) -> None:
        prs = fx.blank_presentation()
        fx.add_chart_slide(prs)
        with mock.patch.object(PptxReader, "_describe_chart", side_effect=RuntimeError("boom")):
            page = self.read(prs).pages[0]

        self.assertNotIn("[Chart]", page.text)
        self.assertTrue(any("could not be read" in w for w in page.warnings))
        self.assertLess(page.confidence, 1.0)

    def test_chart_with_no_content_is_reported_unreadable(self) -> None:
        prs = fx.blank_presentation()
        fx.add_chart_slide(prs)
        with mock.patch.object(PptxReader, "_describe_chart", return_value=[]):
            page = self.read(prs).pages[0]

        self.assertTrue(page.warnings)
        self.assertEqual(page.confidence, 0.5)


class ImageOcrTests(PptxReaderTestCase):
    def test_duplicate_images_are_ocred_once(self) -> None:
        prs = fx.blank_presentation()
        first = prs.slides.add_slide(prs.slide_layouts[fx.LAYOUT_BLANK])
        fx.add_picture(first, self.dir, "logo_a.png", color="white", top=1)
        fx.add_picture(first, self.dir, "logo_b.png", color="white", top=3)
        second = prs.slides.add_slide(prs.slide_layouts[fx.LAYOUT_BLANK])
        fx.add_picture(second, self.dir, "logo_c.png", color="white", top=1)
        doc = self.read(prs)

        self.assertEqual(self.ocr.calls, 1)
        self.assertEqual(doc.statistics["image_count"], 3)
        self.assertEqual(doc.statistics["image_ocr_count"], 3)  # text reused on every slide
        self.assertEqual([i.index for i in doc.pages[0].images], [0, 1])
        self.assertEqual(doc.pages[1].images[0].page_number, 2)

    def test_different_images_are_each_ocred(self) -> None:
        prs = fx.blank_presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[fx.LAYOUT_BLANK])
        fx.add_picture(slide, self.dir, "a.png", color="white", top=1)
        fx.add_picture(slide, self.dir, "b.png", color="black", top=3)
        self.read(prs)

        self.assertEqual(self.ocr.calls, 2)

    def test_ocr_text_reaches_final_text(self) -> None:
        prs = fx.blank_presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[fx.LAYOUT_BLANK])
        fx.add_picture(slide, self.dir, "a.png")
        page = self.read(prs).pages[0]

        self.assertIn("[Embedded Image 1 OCR]\nLOGO TEXT", page.final_text)
        self.assertEqual(page.page_type, PageType.SCANNED_PAGE)

    def test_emf_is_unsupported_not_a_decode_failure(self) -> None:
        emf_blob = b"\x01\x00\x00\x00" + b"\x00" * 36 + b" EMF" + b"not-really-an-image"
        raw = _RawImage(1, 0, emf_blob, "diagram", sha1="emf-1")
        image, warning = self.reader._process_cached(raw, {})

        self.assertEqual(image.ocr_skipped_reason, SKIP_UNSUPPORTED_FORMAT)
        self.assertIn("EMF/WMF image skipped because format is not supported", warning or "")
        self.assertEqual(score_image(image), 0.70)
        self.assertEqual(self.ocr.calls, 0)

    def test_corrupt_png_is_still_a_decode_failure(self) -> None:
        raw = _RawImage(1, 0, b"garbage", "broken", sha1="bad-1", ext="png")
        image, warning = self.reader._process_cached(raw, {})

        self.assertEqual(image.ocr_skipped_reason, SKIP_DECODE_FAILED)
        self.assertIn("decode failed", warning or "")
        self.assertEqual(score_image(image), 0.0)

    def test_cached_failure_warning_uses_current_location(self) -> None:
        cache: dict = {}
        self.reader._process_cached(_RawImage(1, 0, b"garbage", "x", sha1="s"), cache)
        _, warning = self.reader._process_cached(_RawImage(4, 2, b"garbage", "x", sha1="s"), cache)

        self.assertTrue((warning or "").startswith("Slide 4 image 3"))


class TableTests(PptxReaderTestCase):
    def test_horizontal_merge_fills_header_only(self) -> None:
        prs = fx.blank_presentation()
        fx.add_merged_table_slide(prs)
        page = self.read(prs).pages[0]

        rows = page.tables[0].rows
        self.assertEqual(rows[0], ["Group", "Scores", "Scores"])
        self.assertEqual(rows[1], ["A", "1", "2"])
        self.assertNotIn("Column", page.final_text)

    def test_vertical_merge_repeats_origin_text(self) -> None:
        prs = fx.blank_presentation()
        fx.add_vertical_merge_slide(prs)
        rows = self.read(prs).pages[0].tables[0].rows

        self.assertEqual([r[0] for r in rows], ["Topic", "Networks", "Networks"])
        self.assertEqual([r[1] for r in rows], ["Point", "TCP", "UDP"])


class ConfidenceTests(PptxReaderTestCase):
    @staticmethod
    def _image(**kwargs) -> ImageData:
        return ImageData(page_number=1, index=0, xref=0, width=1, height=1, **kwargs)

    def test_no_images_or_charts_is_full_confidence(self) -> None:
        self.assertEqual(compute_confidence([]), 1.0)

    def test_failure_scores_zero_and_unsupported_is_milder(self) -> None:
        failed = self._image(ocr_skipped_reason=SKIP_DECODE_FAILED)
        unsupported = self._image(ocr_skipped_reason=SKIP_UNSUPPORTED_FORMAT)

        self.assertEqual(compute_confidence([failed]), 0.0)
        self.assertEqual(compute_confidence([unsupported]), 0.7)

    def test_successful_ocr_scales_with_engine_confidence(self) -> None:
        good = self._image(ocr_text="x", ocr_applied=True, ocr_confidence=100.0)
        fair = self._image(ocr_text="x", ocr_applied=True, ocr_confidence=0.0)

        self.assertEqual(compute_confidence([good]), 1.0)
        self.assertEqual(compute_confidence([fair]), 0.85)

    def test_charts_take_part_in_the_mean(self) -> None:
        good = self._image(ocr_text="x", ocr_applied=True, ocr_confidence=100.0)

        self.assertEqual(compute_confidence([good], [0.5]), 0.75)
        self.assertEqual(compute_confidence([], [0.5]), 0.5)


class ErrorHandlingTests(PptxReaderTestCase):
    def test_missing_file(self) -> None:
        with self.assertRaises(PptxParseError):
            self.reader.read(self.dir / "nope.pptx")

    def test_wrong_extension(self) -> None:
        path = self.dir / "notes.txt"
        path.write_text("hi")
        with self.assertRaises(PptxParseError):
            self.reader.read(path)

    def test_corrupt_file(self) -> None:
        path = self.dir / "broken.pptx"
        path.write_bytes(b"this is not a zip")
        with self.assertRaises(PptxParseError):
            self.reader.read(path)

    def test_convenience_function(self) -> None:
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "Hello", [("a", 0)])
        doc = read_pptx(fx.save(prs, self.dir), ocr_processor=self.ocr)  # type: ignore[arg-type]

        self.assertEqual(doc.statistics["slide_count"], 1)
        self.assertEqual(doc.metadata["file_type"], "pptx")


if __name__ == "__main__":
    unittest.main()

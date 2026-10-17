"""PDF text-quality tests: wrapped headings, bullets, repeated headers/footers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.ingestion.models import BlockType, Document, ImageData, PageContent
from ai.ingestion.pdf_reader import (
    PDFReader,
    RunningLines,
    _Span,
    is_bullet_glyph,
    running_key,
    split_bullet,
)
from tests import pdf_fixtures as pf


class PdfQualityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.pipeline = IngestionPipeline()

    def ingest(self, pages, name: str = "doc.pdf", **options) -> Document:
        return self.pipeline.ingest(pf.make_pdf(self.dir / name, pages, **options))

    @staticmethod
    def headings(doc: Document) -> list[tuple[str, int | None]]:
        return [(b.text, b.level) for b in doc.blocks if b.is_heading]


class WrappedHeadingTests(PdfQualityTestCase):
    def test_two_line_heading_becomes_one_block(self) -> None:
        pages = [[("Introduction to Distributed", 24.0), ("Systems", 24.0), *pf.body()]]
        doc = self.ingest(pages, leading=1.25)

        self.assertEqual(self.headings(doc), [("Introduction to Distributed Systems", 1)])
        self.assertIn("# Introduction to Distributed Systems", doc.pages[0].final_text)
        body = next(b for b in doc.blocks if b.type is BlockType.PARAGRAPH)
        self.assertEqual(body.heading_path, ("Introduction to Distributed Systems",))

    def test_three_line_heading_is_merged(self) -> None:
        pages = [[("A Long Title That", 24.0), ("Wraps Over Three", 24.0), ("Lines Of Text", 24.0),
                  *pf.body()]]
        doc = self.ingest(pages, leading=1.25)

        self.assertEqual(self.headings(doc), [("A Long Title That Wraps Over Three Lines Of Text", 1)])

    def test_hyphenated_wrap_is_rejoined_without_space(self) -> None:
        pages = [[("Distrib-", 24.0), ("uted Systems", 24.0), *pf.body()]]
        doc = self.ingest(pages, leading=1.25)

        self.assertEqual(self.headings(doc)[0][0], "Distributed Systems")

    def test_following_heading_nests_under_the_merged_one(self) -> None:
        pages = [[("Distributed Systems", 24.0), ("Overview", 24.0), ("Basics", 16.0),
                  *pf.body()]]
        doc = self.ingest(pages, leading=1.25)

        titles = {b.text: b.heading_path for b in doc.blocks if b.is_heading}
        self.assertEqual(
            titles,
            {
                "Distributed Systems Overview": ("Distributed Systems Overview",),
                "Basics": ("Distributed Systems Overview", "Basics"),
            },
        )

    def test_cover_title_and_smaller_subtitle_are_not_merged(self) -> None:
        # Two pages: the 32pt size is cover-only, so it ranks like the 15pt line.
        pages = [
            [("IntelliStudy", 32.0), ("AI-Powered Lecture Summarization", 15.0), *pf.body()],
            [("Second page heading", 15.0), *pf.body()],
        ]
        doc = self.ingest(pages, leading=1.25)

        self.assertEqual(
            [t for t, _ in self.headings(doc)][:2],
            ["IntelliStudy", "AI-Powered Lecture Summarization"],
        )

    def test_headings_far_apart_stay_separate(self) -> None:
        pages = [[("First Topic", 24.0), ("Second Topic", 24.0), *pf.body()]]
        doc = self.ingest(pages, leading=2.6)

        self.assertEqual([t for t, _ in self.headings(doc)], ["First Topic", "Second Topic"])

    def test_different_sizes_are_not_merged(self) -> None:
        pages = [[("Chapter Title", 24.0), ("Section", 16.0), *pf.body()]]
        doc = self.ingest(pages, leading=1.25)

        self.assertEqual(self.headings(doc), [("Chapter Title", 1), ("Section", 2)])

    def test_consecutive_numbered_headings_are_not_merged(self) -> None:
        pages = [[("1. Introduction", 18.0), ("2. Methods", 18.0), *pf.body()]]
        doc = self.ingest(pages, leading=1.25)

        self.assertEqual([t for t, _ in self.headings(doc)], ["1. Introduction", "2. Methods"])

    def test_centred_wrapped_title_is_merged(self) -> None:
        def draw(page, _number) -> None:
            width = page.rect.width
            for text, y in (("Concepts of Aspect-Oriented", 120), ("Development", 150)):
                real = fitz.get_text_length(text, fontname="helv", fontsize=24)
                page.insert_text(((width - real) / 2, y), text, fontsize=24)
            for index, (text, size) in enumerate(pf.body()):
                page.insert_text((72, 260 + index * 20), text, fontsize=size)

        doc = self.pipeline.ingest(pf.make_custom_pdf(self.dir / "centred.pdf", draw))

        self.assertEqual(self.headings(doc)[0][0], "Concepts of Aspect-Oriented Development")


class RunInBulletParagraphTests(PdfQualityTestCase):
    def test_larger_run_in_bullet_paragraph_is_body_text_not_headings(self) -> None:
        # Regression (data/uploads/test2.pdf): a 12 pt paragraph of "a. - b. - c." lines
        # next to 10 pt table text was read as two headings.
        bullet = chr(0x2022)

        def draw(page: fitz.Page, _index: int) -> None:
            y = 72.0
            for line in (
                f"System design. {bullet} UI wireframes and data model. {bullet}",
                f"Document processing pipeline. {bullet} Embedding generation and",
                f"vector database integration. {bullet} RAG retrieval system. {bullet}",
                f"Summarization module. {bullet} Quiz generation module.",
            ):
                page.insert_text((72, y), line, fontsize=12)
                y += 17
            for row in range(12):
                page.insert_text((72, 200 + row * 14), f"small table style text row {row} with more words", fontsize=10)

        doc = self.pipeline.ingest(pf.make_custom_pdf(self.dir / "runin.pdf", draw))

        self.assertEqual([b.text for b in doc.blocks if b.is_heading], [])
        self.assertIn("UI wireframes", " ".join(b.text for b in doc.blocks))


class DocumentLevelHeadingTests(PdfQualityTestCase):
    def test_equal_sized_titles_get_equal_levels_despite_different_body_sizes(self) -> None:
        small = [(text, 11.0) for text in pf.BODY_LINES]
        large = [(text, 16.0) for text in pf.BODY_LINES]
        pages = [
            [("Alpha Topic", 28.0), *small],
            [("Beta Topic", 28.0), *large],
            [("Gamma Topic", 28.0), *small],
        ]
        doc = self.ingest(pages)

        self.assertEqual([lvl for _, lvl in self.headings(doc)], [1, 1, 1])
        paths = {b.text: b.heading_path for b in doc.blocks if b.is_heading}
        self.assertEqual(paths["Beta Topic"], ("Beta Topic",))  # sibling, not nested

    def test_sizes_are_ranked_across_the_whole_document(self) -> None:
        pages = [
            [("Big Title", 30.0), ("Sub Title", 20.0), *pf.body()],
            [("Big Title Two", 30.0), ("Sub Title Two", 20.0), *pf.body()],
            [("Big Title Three", 30.0), *pf.body()],
        ]
        doc = self.ingest(pages)

        levels = dict(self.headings(doc))
        self.assertEqual(levels["Big Title"], 1)
        self.assertEqual(levels["Sub Title"], 2)
        self.assertEqual(levels["Big Title Three"], 1)

    def test_table_of_contents_dot_leader_rows_are_dropped(self) -> None:
        pages = [[("Contents", 18.0),
                  ("1. Introduction .......................... 3", 11.0),
                  ("2. Methods ............................... 7", 11.0),
                  *pf.body()]]
        doc = self.ingest(pages)

        self.assertNotIn("....", doc.full_text)
        self.assertIn("This sentence is plain body text", doc.full_text)


class BulletTests(PdfQualityTestCase):
    def test_glyph_variants_normalise_to_dash_items(self) -> None:
        pages = [[("Course Topics", 24.0),
                  ("• First topic of the course", 14.0),
                  ("- Second topic of the course", 14.0),
                  ("o Third topic of the course", 14.0),
                  *pf.body()]]
        doc = self.ingest(pages)

        items = [b for b in doc.blocks if b.type is BlockType.LIST_ITEM]
        self.assertEqual(
            [i.text for i in items],
            ["First topic of the course", "Second topic of the course", "Third topic of the course"],
        )
        self.assertEqual({i.list_marker for i in items}, {"-"})
        self.assertNotIn("•", doc.full_text)
        self.assertEqual(self.headings(doc), [("Course Topics", 1)])  # bullets not promoted

    def test_larger_bullet_text_is_not_a_heading(self) -> None:
        pages = [[("• Bullet set larger than the body text", 18.0), *pf.body()]]
        doc = self.ingest(pages)

        self.assertEqual(self.headings(doc), [])
        self.assertEqual(doc.statistics["list_item_count"], 1)

    def test_courier_o_bullet_in_its_own_span_does_not_glue(self) -> None:
        def draw(page, _number) -> None:
            for index, text in enumerate(["Separation of concerns", "Aspect-oriented design"]):
                y = 100 + index * 26
                page.insert_text((90, y), "o", fontname="cour", fontsize=14)
                page.insert_text((110, y), text, fontname="helv", fontsize=14)
            for index, (text, size) in enumerate(pf.body()):
                page.insert_text((72, 300 + index * 20), text, fontsize=size)

        doc = self.pipeline.ingest(pf.make_custom_pdf(self.dir / "courier.pdf", draw))

        items = [b.text for b in doc.blocks if b.type is BlockType.LIST_ITEM]
        self.assertEqual(items, ["Separation of concerns", "Aspect-oriented design"])
        self.assertNotIn("oSeparation", doc.full_text)

    def test_wrapped_bullet_lines_are_rejoined(self) -> None:
        def draw(page, _number) -> None:
            page.insert_text((72, 100), "•", fontsize=14)
            page.insert_text((92, 100), "A long list item that wraps onto", fontsize=14)
            page.insert_text((92, 118), "a second line of text.", fontsize=14)
            page.insert_text((72, 150), "•", fontsize=14)
            page.insert_text((92, 150), "A short item.", fontsize=14)
            for index, (text, size) in enumerate(pf.body()):
                page.insert_text((72, 300 + index * 20), text, fontsize=size)

        doc = self.pipeline.ingest(pf.make_custom_pdf(self.dir / "wrap.pdf", draw))

        items = [b.text for b in doc.blocks if b.type is BlockType.LIST_ITEM]
        self.assertEqual(
            items,
            ["A long list item that wraps onto a second line of text.", "A short item."],
        )

    def test_nested_bullets_get_depth_from_indent(self) -> None:
        def draw(page, _number) -> None:
            page.insert_text((72, 100), "• Parent item of the list", fontsize=14)
            page.insert_text((108, 130), "o Child item of the parent", fontsize=14)
            page.insert_text((72, 160), "• Second parent item", fontsize=14)
            for index, (text, size) in enumerate(pf.body()):
                page.insert_text((72, 300 + index * 20), text, fontsize=size)

        doc = self.pipeline.ingest(pf.make_custom_pdf(self.dir / "nested.pdf", draw))

        items = [(b.text, b.level) for b in doc.blocks if b.type is BlockType.LIST_ITEM]
        self.assertEqual(
            items,
            [("Parent item of the list", 0), ("Child item of the parent", 1),
             ("Second parent item", 0)],
        )
        self.assertIn("  - Child item of the parent", doc.pages[0].final_text)

    def test_ordinary_words_are_not_bullets(self) -> None:
        pages = [[("Overview of the okay results", 11.0),
                  ("-5 degrees is the observed minimum value", 11.0),
                  ("other observations follow the data set", 11.0),
                  *pf.body()]]
        doc = self.ingest(pages)

        self.assertEqual(doc.statistics["list_item_count"], 0)
        self.assertIn("-5 degrees", doc.full_text)

    def test_split_bullet_glyph_catalogue(self) -> None:
        def spans(*parts: tuple[str, str]) -> list[_Span]:
            x = 0.0
            out = []
            for text, font in parts:
                out.append(_Span(text, font, x, x + 10))
                x += 12
            return out

        for glyph in ["•", "○", "▪", "●", "‣", "·", "",
                      "", "\ufffd"]:
            with self.subTest(glyph=repr(glyph)):
                self.assertTrue(is_bullet_glyph(glyph))
                result = split_bullet(spans((glyph, "Symbol"), ("Item text", "Arial")),
                                      f"{glyph}Item text")
                self.assertEqual(result[0], "Item text")  # type: ignore[index]
                same_span = split_bullet(spans((f"{glyph} Item text", "Arial")), f"{glyph} Item text")
                self.assertEqual(same_span[0], "Item text")  # type: ignore[index]

    def test_split_bullet_rejects_plain_text(self) -> None:
        for text in ["Regular sentence", "okay then", "Overview", "3 items", "a - b"]:
            with self.subTest(text=text):
                self.assertIsNone(split_bullet([_Span(text, "Arial", 0, 10)], text))

    def test_glyph_only_row_is_not_a_bullet(self) -> None:
        self.assertIsNone(split_bullet([_Span("•", "Arial", 0, 10)], "•"))


class RunningHeaderFooterTests(PdfQualityTestCase):
    # Body text starts below the header band (top 18% of an A4 page is ~150pt);
    # otherwise identical body lines on every page would themselves be running content.
    BODY_START = 200.0

    def ingest(self, pages, name: str = "doc.pdf", **options) -> Document:  # type: ignore[override]
        options.setdefault("start_y", self.BODY_START)
        return super().ingest(pages, name, **options)

    @staticmethod
    def six_pages() -> list[list[tuple[str, float]]]:
        return [
            [(f"Section {n} Title", 20.0), *pf.body(f"Unique sentence number {n} on this page.")]
            for n in range(1, 7)
        ]

    def test_header_and_footer_are_removed_everywhere(self) -> None:
        doc = self.ingest(
            self.six_pages(),
            header="IntelliStudy - Graduation Project Proposal",
            footer="Page {n} of {total}",
        )

        full = doc.full_text
        self.assertNotIn("IntelliStudy - Graduation Project Proposal", full)
        self.assertNotIn("Page 3 of 6", full)
        for block in doc.blocks:
            self.assertNotIn("Graduation Project", block.text)
            self.assertNotRegex(block.text, r"Page \d+ of 6")
        self.assertIn("Unique sentence number 4 on this page.", full)

        info = doc.metadata["running_content"]["lines"]
        self.assertEqual(
            sorted((i["pattern"], i["zone"]) for i in info),
            [("intellistudy - graduation project proposal", "header"), ("page # of #", "footer")],
        )

    def test_institution_line_as_footer(self) -> None:
        doc = self.ingest(self.six_pages(), footer="Faculty of Engineering")

        self.assertNotIn("Faculty of Engineering", doc.full_text)

    def test_bare_page_numbers_are_removed(self) -> None:
        doc = self.ingest(self.six_pages(), footer="{n}")

        for block in doc.blocks:
            self.assertNotRegex(block.text.strip(), r"^\d+$")
        self.assertEqual(len(doc.metadata["running_content"]["lines"]), 1)

    def test_line_on_few_pages_is_kept(self) -> None:
        pages = self.six_pages()
        path = pf.make_pdf(self.dir / "few.pdf", pages, start_y=self.BODY_START)

        def stamp_two_pages(page, number) -> None:
            if number <= 2:
                page.insert_text((72, 30), "DRAFT - do not distribute", fontsize=9)

        document = fitz.open(str(path))
        for number, page in enumerate(document, start=1):
            stamp_two_pages(page, number)
        stamped = self.dir / "few-stamped.pdf"
        document.save(str(stamped))
        document.close()
        doc = self.pipeline.ingest(stamped)

        self.assertIn("DRAFT - do not distribute", doc.full_text)
        self.assertNotIn("running_content", doc.metadata)

    def test_repeated_text_in_the_body_is_kept(self) -> None:
        pages = [
            [("Summary", 20.0), *pf.body(f"Unique sentence number {n} on this page.")]
            for n in range(1, 7)
        ]
        doc = self.ingest(pages, start_y=300.0)  # title sits mid-page, outside the bands

        titles = [b.text for b in doc.blocks if b.is_heading]
        self.assertEqual(titles.count("Summary"), 6)

    def test_unstable_position_is_not_running_content(self) -> None:
        def draw(page, number) -> None:
            page.insert_text((72, 25 + number * 18), "Chapter banner", fontsize=9)
            for index, (text, size) in enumerate(pf.body(f"Unique sentence {number}.")):
                page.insert_text((72, 300 + index * 20), text, fontsize=size)

        doc = self.pipeline.ingest(pf.make_custom_pdf(self.dir / "moving.pdf", draw, pages=6))

        self.assertEqual(doc.full_text.count("Chapter banner"), 6)

    def test_short_documents_are_left_alone(self) -> None:
        pages = self.six_pages()[:2]
        doc = self.ingest(pages, header="Course Notes", footer="Page {n} of {total}")

        self.assertIn("Course Notes", doc.full_text)
        self.assertIn("Page 2 of 2", doc.full_text)

    def test_running_lines_value_object(self) -> None:
        running = RunningLines(patterns=(("page # of #", "footer", 0.95, 10),))

        self.assertTrue(running.matches("Page 12 of 40", 800.0, 842.0))
        self.assertFalse(running.matches("Page 12 of 40", 400.0, 842.0))  # wrong height
        self.assertFalse(running.matches("Something else", 800.0, 842.0))
        self.assertFalse(RunningLines().matches("Page 1", 800.0, 842.0))
        self.assertEqual(running_key("Page 12 of  40"), "page # of #")

    def test_reader_detection_directly(self) -> None:
        path = pf.make_pdf(
            self.dir / "d.pdf", self.six_pages(), header="Course Notes", start_y=self.BODY_START
        )
        reader = PDFReader()
        document = reader.open(path)
        try:
            running = reader.detect_running_lines(document)
        finally:
            document.close()

        self.assertEqual([p[0] for p in running.patterns], ["course notes"])


class RepeatedImageTests(unittest.TestCase):
    @staticmethod
    def page(number: int, *texts: str) -> PageContent:
        images = [
            ImageData(page_number=number, index=i, xref=i, width=100, height=100,
                      ocr_text=text, ocr_applied=True, ocr_confidence=90.0)
            for i, text in enumerate(texts)
        ]
        return PageContent(page_number=number, images=images)

    def test_logo_text_repeated_on_most_pages_is_dropped(self) -> None:
        pages = [self.page(n, "Ain Shams University", f"Figure {n} caption text") for n in range(1, 7)]
        removed = IngestionPipeline._drop_repeated_images(pages)

        self.assertEqual(removed, 6)
        for page in pages:
            self.assertEqual([i.ocr_text for i in page.images_with_text],
                             [f"Figure {page.page_number} caption text"])
            self.assertEqual(page.images[0].ocr_skipped_reason, "repeated")

    def test_small_documents_are_untouched(self) -> None:
        pages = [self.page(1, "Logo"), self.page(2, "Logo")]

        self.assertEqual(IngestionPipeline._drop_repeated_images(pages), 0)
        self.assertEqual(len(pages[0].images_with_text), 1)


if __name__ == "__main__":
    unittest.main()

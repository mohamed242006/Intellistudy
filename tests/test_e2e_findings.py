"""Failing-first tests for defects found by the 30-file end-to-end validation (data/uploads/{docs,PDFs,pptx}).

Each class names the finding (E2E-nn) and the real file that exposed it.
"""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz
from pptx.util import Inches

from ai.chunking import ChunkingEngine
from ai.ingestion.cleaners import clean_text
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.ingestion.models import Block, BlockType, PageContent, TableData
from ai.ingestion.pptx_reader import PptxReader
from tests import pdf_fixtures as pf
from tests import pptx_fixtures as fx
from tests.chunk_fixtures import CTX, SMALL, H, Pg, WordCounter, build, words


def engine() -> ChunkingEngine:
    return ChunkingEngine(SMALL, WordCounter())


class E2E01MergedSectionsKeepTheirTitles(unittest.TestCase):
    """docs/sample-files.com-large-document.docx: 23 of ~60 headings (2.1, 3.1, 6.2 ...) appeared in no chunk.

    Small sibling sections are merged and the chunk path shrinks to the common ancestor, so
    the DOCX citation named only the document title and the section titles were not embedded.
    """

    def test_every_merged_section_title_is_in_the_text_of_its_chunk(self) -> None:
        doc = build([
            H("Guide", 1),
            H("Alpha", 2), Pg(words(3, "a")),
            H("Beta", 2), Pg(words(3, "b")),
            H("Gamma", 2), Pg(words(3, "g")),
        ], unit="document", file_type="docx")
        chunks = engine().run(doc, CTX).children

        for title, marker in (("Alpha", "a0"), ("Beta", "b0"), ("Gamma", "g0")):
            with self.subTest(title=title):
                owner = next(c for c in chunks if marker in c.text)
                self.assertIn(title, owner.text, "section title must travel with the text it introduces")
                self.assertIn(title, owner.embedding_text)


class E2E02TablePipeCharacterIsPreserved(unittest.TestCase):
    """docs/sample-files.com-large-document.docx: the regex table cell 'cat|dog' became 'cat/dog'."""

    def test_pipe_inside_a_cell_is_escaped_not_replaced(self) -> None:
        rows = [["Pattern", "Example"], ["a|b", "cat|dog"]]
        table = TableData(page_number=1, index=0, rows=rows)
        doc = build(
            [H("Regex"), Block(BlockType.TABLE, "x", 1, ref_index=0)],
            pages=[PageContent(page_number=1, tables=[table])],
        )
        text = next(c for c in engine().run(doc, CTX).children if c.kind == "table").text

        self.assertNotIn("cat/dog", text)
        self.assertIn(r"cat\|dog", text)
        self.assertIn(r"a\|b", text)


class E2E03SymbolFontGlyphsAreMapped(unittest.TestCase):
    """pptx/SPE_l1.pptx (134 blocks) and PDFs/hard_PDF_2,5,6,9: private-use glyphs reached the chunks.

    'M/M/c/\\uf0a5/N' is the infinity sign of the Symbol font; \\uf8f1..\\uf8f8 are the pieces of
    big braces and parentheses (Adobe Symbol private-use area).
    """

    def test_no_private_use_characters_survive_cleaning(self) -> None:
        raw = "queue M/M/c//N  longer wait     \n\n \n\n"
        cleaned = clean_text(raw)

        leftovers = [hex(ord(ch)) for ch in cleaned if 0xE000 <= ord(ch) <= 0xF8FF]
        self.assertEqual(leftovers, [])

    def test_symbol_font_math_glyphs_become_their_unicode_math_characters(self) -> None:
        self.assertEqual(clean_text("c//N"), "c/∞/N")
        self.assertEqual(clean_text("a  b"), "a ⇒ b")
        self.assertEqual(clean_text("  "), "α μ λ")
        self.assertEqual(clean_text("x  y"), "x ≥ y")
        self.assertEqual(clean_text(""), "⎧")


class E2E04EmptyTablesAreNotBlocks(unittest.TestCase):
    """Slidesgo decks: slide 46/47 produced 4 table blocks with empty text (decorative empty tables)."""

    def test_table_with_only_empty_cells_produces_no_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            prs = fx.blank_presentation()
            slide = fx.add_bullet_slide(prs, "Layout", [("Some real text", 0)])
            slide.shapes.add_table(2, 2, Inches(1), Inches(4), Inches(4), Inches(1))  # all cells empty
            path = fx.save(prs, Path(tmp))
            doc = PptxReader(ocr_processor=fx.FakeOCR()).read(path)  # type: ignore[arg-type]

        empty = [b for b in doc.blocks if b.type == BlockType.TABLE and not b.text.strip()]
        self.assertEqual(empty, [])
        self.assertEqual(doc.statistics["table_count"], sum(1 for b in doc.blocks if b.type == BlockType.TABLE))


class E2E05RotatedMarginStampIsNotAHeading(unittest.TestCase):
    """PDFs/hard_PDF_2..10 (arXiv papers): the rotated 20 pt margin stamp 'arXiv:2610.05884v1 [math.AC]' became a
    level-1 heading, so 9 of 10 documents had it as the root of every chunk's heading_path and citation.
    """

    STAMP = "arXiv:2610.05884v1 [math.AC] 5 Oct 2026"

    def test_rotated_margin_text_is_not_a_heading_or_a_path_root(self) -> None:
        def draw(page: fitz.Page, number: int) -> None:
            page.insert_text((300, 72), "ON INJECTIVE COMPLEXES", fontsize=14)
            y = 110.0
            for line in pf.body("The aim of this paper is to study complexes.", "Here is one more ordinary sentence."):
                page.insert_text((72, y), line[0], fontsize=line[1])
                y += 18
            page.insert_text((30, 600), self.STAMP, fontsize=20, rotate=90)

        with tempfile.TemporaryDirectory() as tmp:
            doc = IngestionPipeline().ingest(pf.make_custom_pdf(Path(tmp) / "paper.pdf", draw, pages=2))

        self.assertNotIn(self.STAMP, [b.text for b in doc.blocks if b.type == BlockType.HEADING])
        for block in doc.blocks:
            self.assertNotIn("arXiv", " ".join(block.heading_path), block.text[:40])


class E2E06OutlineEntriesBecomeHeadings(unittest.TestCase):
    """PDFs/hard_PDF_*: section titles in small caps ('1. PRELIMINARIES', 'REFERENCES') were paragraphs, so the papers
    had no section structure even though the PDF carries a bookmark outline for each of them.
    """

    def test_paragraph_matching_a_bookmark_on_its_page_is_promoted_to_a_heading(self) -> None:
        pages = [
            [("0. INTRODUCTION", pf.BODY_SIZE), *pf.body("We study injective complexes in algebra.")],
            [("1. PRELIMINARIES", pf.BODY_SIZE), *pf.body("Recall the definition of a complex.")],
        ]
        toc = [[1, "0. Introduction", 1], [1, "1. Preliminaries", 2]]
        with tempfile.TemporaryDirectory() as tmp:
            doc = IngestionPipeline().ingest(pf.make_pdf(Path(tmp) / "paper.pdf", pages, toc=toc))

        self.assertEqual(
            [(b.text, b.level) for b in doc.blocks if b.type == BlockType.HEADING],
            [("0. INTRODUCTION", 1), ("1. PRELIMINARIES", 1)],
        )
        body_block = next(b for b in doc.blocks if "Recall the definition" in b.text)
        self.assertEqual(body_block.heading_path, ("1. PRELIMINARIES",))

    def test_bookmark_without_section_number_matches_numbered_title_in_the_text(self) -> None:
        # PDFs/hard_PDF_2.pdf: bookmark 'Introduction' / 'Embedding Dimension 3', page text '1. Introduction'.
        pages = [
            [("1. Introduction", pf.BODY_SIZE), *pf.body("We study numerical monoids here.")],
            [("4. Embedding Dimension 3", pf.BODY_SIZE), *pf.body("The case of three generators follows.")],
        ]
        toc = [[1, "Introduction", 1], [1, "Embedding Dimension 3", 2]]
        with tempfile.TemporaryDirectory() as tmp:
            doc = IngestionPipeline().ingest(pf.make_pdf(Path(tmp) / "paper.pdf", pages, toc=toc))

        self.assertEqual(
            [b.text for b in doc.blocks if b.type == BlockType.HEADING],
            ["1. Introduction", "4. Embedding Dimension 3"],
        )

    def test_body_sentence_that_merely_contains_the_title_is_not_promoted(self) -> None:
        pages = [[*pf.body("Next we discuss 1. Preliminaries again in the text.")]]
        toc = [[1, "1. Preliminaries", 1]]
        with tempfile.TemporaryDirectory() as tmp:
            doc = IngestionPipeline().ingest(pf.make_pdf(Path(tmp) / "p.pdf", pages, toc=toc))

        self.assertEqual([b for b in doc.blocks if b.type == BlockType.HEADING], [])



class OpenFindings(unittest.TestCase):
    """Reproducible tests for findings that are reported but NOT fixed yet (expected failures).

    When one is fixed, remove its ``expectedFailure`` marker so it guards against regression.
    """

    def test_e2e07_slide_title_typed_in_a_plain_text_box_becomes_a_heading(self) -> None:
        # pptx/University Admission Slides, SlideEgg Research University, University Research Poster:
        # no title placeholder -> no heading -> chunks cited only as 'slide N' and embedded without topic.
        with tempfile.TemporaryDirectory() as tmp:
            prs = fx.blank_presentation()
            slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout, no placeholders
            title = slide.shapes.add_textbox(Inches(1), Inches(0.3), Inches(8), Inches(1))
            title.text_frame.text = "Admission Requirements"
            title.text_frame.paragraphs[0].runs[0].font.size = Inches(0.5)
            body = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(3))
            body.text_frame.text = "Applicants submit transcripts and two reference letters."
            doc = PptxReader(ocr_processor=fx.FakeOCR()).read(fx.save(prs, Path(tmp)))  # type: ignore[arg-type]

        self.assertIn("Admission Requirements", [b.text for b in doc.blocks if b.type == BlockType.HEADING])

    @staticmethod
    def _text_box_slide(texts: list[tuple[str, int]]):
        """Blank-layout slide with one plain text box per ``(text, font points)`` entry."""
        from pptx.util import Pt

        prs = fx.blank_presentation()
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        for position, (text, points) in enumerate(texts):
            box = slide.shapes.add_textbox(Inches(1), Inches(0.5 + position), Inches(8), Inches(0.8))
            box.text_frame.text = text
            box.text_frame.paragraphs[0].runs[0].font.size = Pt(points)
        return prs

    def _headings(self, prs) -> list[str]:
        with tempfile.TemporaryDirectory() as tmp:
            doc = PptxReader(ocr_processor=fx.FakeOCR()).read(fx.save(prs, Path(tmp)))  # type: ignore[arg-type]
        return [b.text for b in doc.blocks if b.type == BlockType.HEADING]

    def test_e2e07_two_equally_large_boxes_are_ambiguous_so_no_title_is_guessed(self) -> None:
        prs = self._text_box_slide([("Mission", 40), ("Vision", 40), ("Details follow in the notes below.", 14)])
        self.assertEqual(self._headings(prs), [])

    def test_e2e07_small_or_numeric_or_sentence_text_is_never_a_title(self) -> None:
        for texts in (
            [("Quarterly overview", 14), ("body text here", 12)],  # below the minimum size
            [("01", 60), ("body text here", 12)],  # a number
            [("This sentence is clearly a body paragraph.", 30), ("x", 12)],  # ends with a full stop
        ):
            with self.subTest(texts=texts):
                self.assertEqual(self._headings(self._text_box_slide(texts)), [])

    def test_e2e07_title_placeholder_still_wins_over_a_larger_text_box(self) -> None:
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "Real Title", [("point", 0)])
        from pptx.util import Pt

        extra = prs.slides[0].shapes.add_textbox(Inches(1), Inches(6), Inches(4), Inches(1))
        extra.text_frame.text = "Giant decoration"
        extra.text_frame.paragraphs[0].runs[0].font.size = Pt(90)
        self.assertEqual(self._headings(prs), ["Real Title"])

    def test_e2e08_chunk_ids_of_untouched_sections_survive_an_edit_of_the_file(self) -> None:
        # Every re-upload of an edited file changed ALL chunk ids (ids embedded the file hash), although
        # vectors were reused. Observed on 6 edited real files: ids surviving = 0%.
        blocks = [H("A"), Pg(words(30, "a")), H("B"), Pg(words(30, "b"))]
        before = build(blocks)
        after = build([H("A"), Pg(words(30, "a")), H("B"), Pg(words(30, "b") + " edited")])
        assert before.source is not None and after.source is not None
        after.source = dataclasses.replace(after.source, doc_id="d0c0000000000002", sha256="1" * 64)
        ids_before = [c.chunk_id for c in engine().run(before, CTX).children]
        ids_after = [c.chunk_id for c in engine().run(after, CTX).children]

        self.assertEqual(ids_before[0], ids_after[0])

    @unittest.expectedFailure
    def test_e2e09_citation_of_a_merged_chunk_names_its_first_section(self) -> None:
        # docs/sample-files.com-large-document.docx: a chunk starting at '6.2 Page Margins and Size'
        # is cited only as 'Sample Large Multi-Section Document' (the common ancestor).
        doc = build([
            H("Guide", 1),
            H("Alpha", 2), Pg(words(3, "a")),
            H("Beta", 2), Pg(words(3, "b")),
        ], unit="document", file_type="docx")
        merged = next(c for c in engine().run(doc, CTX).children if "a0" in c.text)

        self.assertIn("Alpha", merged.citation_label)


if __name__ == "__main__":
    unittest.main()


class E2E08ChunkIdStabilityTests(unittest.TestCase):
    """Ids depend on a chunk's own text only: edits elsewhere never rename it (E2E-08)."""

    @staticmethod
    def document(blocks, doc_id: str = "d0c0000000000001"):
        doc = build(blocks)
        assert doc.source is not None
        doc.source = dataclasses.replace(doc.source, doc_id=doc_id, sha256=doc_id * 4)
        return doc

    def ids(self, blocks, doc_id: str = "d0c0000000000001") -> list[str]:
        return [c.chunk_id for c in engine().run(self.document(blocks, doc_id), CTX).children]

    def test_inserting_a_section_at_the_top_does_not_rename_the_others(self) -> None:
        base = [H("A"), Pg(words(30, "a")), H("B"), Pg(words(30, "b")), H("C"), Pg(words(30, "c"))]
        before = self.ids(base)
        after = self.ids([H("New"), Pg(words(30, "n")), *base], doc_id="d0c0000000000002")
        self.assertEqual(set(before) - set(after), set())  # every old id is still there
        self.assertEqual(len(after) - len(before), 1)

    def test_editing_one_section_changes_only_its_ids(self) -> None:
        base = [H("A"), Pg(words(30, "a")), H("B"), Pg(words(30, "b")), H("C"), Pg(words(30, "c"))]
        edited = [H("A"), Pg(words(30, "a")), H("B"), Pg(words(30, "b") + " changed"), H("C"), Pg(words(30, "c"))]
        before, after = self.ids(base), self.ids(edited, doc_id="d0c0000000000002")
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(set(before) & set(after)), len(before) - 1)

    def test_identical_texts_get_distinct_ids_in_a_stable_order(self) -> None:
        repeated = [H("A"), Pg(words(30, "x")), H("B"), Pg(words(30, "x"))]
        ids = self.ids(repeated)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, self.ids(repeated, doc_id="d0c0000000000009"))

    def test_the_file_hash_never_appears_in_an_id(self) -> None:
        children = engine().run(self.document([H("A"), Pg(words(30, "a"))], doc_id="d0c0000000000007"), CTX)
        for chunk in (*children.children, *children.parents):
            self.assertNotIn("d0c0000000000007", chunk.chunk_id)

    def test_reindexing_an_edited_file_touches_only_the_changed_chunks(self) -> None:
        from ai.chunking import IndexingService, InMemoryVectorStore
        from ai.chunking.memory_store import InMemoryParentStore
        from tests.chunk_fixtures import FakeEmbedder

        base = [H("A"), Pg(words(30, "a")), H("B"), Pg(words(30, "b")), H("C"), Pg(words(30, "c"))]
        edited = [H("A"), Pg(words(30, "a")), H("B"), Pg(words(30, "b") + " changed"), H("C"), Pg(words(30, "c"))]
        embedder = FakeEmbedder(dimension=64)
        indexer = IndexingService(embedder, InMemoryVectorStore(), parent_store=InMemoryParentStore())
        first = engine().run(self.document(base), CTX)
        indexer.index(first.children, document_uid=CTX.document_uid, parents=first.parents)
        second = engine().run(self.document(edited, "d0c0000000000002"), CTX)
        report = indexer.index(second.children, document_uid=CTX.document_uid, parents=second.parents)

        # two of three chunks keep their id and vector; their stored metadata is rewritten (it names the new file hash)
        self.assertEqual(report.unchanged + report.refreshed, 2)
        self.assertEqual(report.reused, 0)
        self.assertEqual(report.embedded, 1)  # only the edited one is embedded
        self.assertEqual(report.deleted, 1)  # and only its old version is removed

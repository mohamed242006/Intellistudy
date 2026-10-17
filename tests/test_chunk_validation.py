"""ChunkValidator (validation tests) and ingestion-schema compatibility (step 6)."""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from docx import Document as new_docx

from ai.chunking.engine import ChunkingEngine
from ai.chunking.errors import ChunkingError, ChunkValidationError
from ai.chunking.models import ChunkSet
from ai.chunking.validation import ChunkValidator
from ai.ingestion.docs_reader import DocxReader
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.ingestion.models import Block, BlockType, PageContent, TableData
from ai.ingestion.pptx_reader import PptxReader
from tests import pdf_fixtures as pf
from tests import pptx_fixtures as fx
from tests.chunk_fixtures import (
    CTX,
    OCR,
    SMALL,
    H,
    Pg,
    WordCounter,
    build,
    sentences,
    slide_meta,
)


def engine(**kwargs) -> ChunkingEngine:
    return ChunkingEngine(SMALL, WordCounter(), **kwargs)


class ValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        table = TableData(page_number=1, index=0, rows=[["A", "B"], ["1", "2"]])
        blocks = [
            H("Sec"), Pg(sentences(3)), Block(BlockType.TABLE, "x", 1, ref_index=0),
            Pg(sentences(3, prefix="z")), OCR("image words recognised", 0.8),
        ]
        self.doc = build(blocks, pages=[PageContent(page_number=1, tables=[table])])
        self.engine = engine()
        self.result = self.engine.run(self.doc, CTX)
        self.validator = self.engine.validator

    def check(self, children=None, parents=None) -> list[str]:
        return self.validator.validate(
            self.doc, children if children is not None else self.result.children,
            parents if parents is not None else self.result.parents,
        )

    def replaced(self, index: int, **changes):
        children = list(self.result.children)
        children[index] = dataclasses.replace(children[index], **changes)
        return children

    def test_clean_result_has_no_problems(self) -> None:
        self.assertEqual(self.check(), [])
        self.assertEqual(self.result.report.problems, [])

    def test_detects_duplicate_ids(self) -> None:
        children = self.replaced(1, chunk_id=self.result.children[0].chunk_id)

        self.assertTrue(any("duplicate" in p for p in self.check(children)))

    def test_detects_orphan_child_and_mismatched_parent_links(self) -> None:
        orphan = self.replaced(0, parent_id="missing")
        self.assertTrue(any("parent" in p for p in self.check(orphan)))

        parents = [dataclasses.replace(self.result.parents[0], child_ids=())] + self.result.parents[1:]
        self.assertTrue(any("child_ids" in p for p in self.check(parents=parents)))

    def test_detects_overlap_on_non_text_chunks(self) -> None:
        index = next(i for i, c in enumerate(self.result.children) if c.kind == "table")
        children = self.replaced(index, overlap_prefix="leaked words")

        self.assertTrue(any("overlap" in p for p in self.check(children)))

    def test_detects_missing_low_confidence_flag_and_indexed_garbage(self) -> None:
        index = next(i for i, c in enumerate(self.result.children) if c.kind == "image_ocr")
        unflagged = self.replaced(index, confidence=0.5, ocr_confidence=0.5, low_confidence=False)
        self.assertTrue(any("flag" in p for p in self.check(unflagged)))

        garbage = self.replaced(index, confidence=0.2, ocr_confidence=0.2, low_confidence=True)
        self.assertTrue(any("0.3" in p for p in self.check(garbage)))

    def test_detects_token_overflow_without_flag(self) -> None:
        children = self.replaced(0, token_count=SMALL.max_tokens + 1)

        self.assertTrue(any("max_tokens" in p for p in self.check(children)))

    def test_detects_lost_blocks(self) -> None:
        children = [c for c in self.result.children if c.kind != "table"]

        self.assertTrue(any("not covered" in p for p in self.check(children, parents=[])))

    def test_detects_slide_crossing(self) -> None:
        blocks = [H("One", page=1), Pg(sentences(3), page=1), H("Two", page=2), Pg(sentences(3), page=2)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=2))
        eng = engine()
        result = eng.run(doc, CTX)
        children = list(result.children)
        children[0] = dataclasses.replace(children[0], page_end=2)

        self.assertTrue(any("slide" in p for p in eng.validator.validate(doc, children, [])))

    def test_detects_hidden_slide_content(self) -> None:
        blocks = [H("One", page=1), Pg(sentences(3), page=1), H("Two", page=2), Pg(sentences(3), page=2)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(2, count=2))
        shown = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=2))
        leaked = engine().run(shown, CTX).children   # chunks that include slide 2

        self.assertTrue(any("hidden" in p for p in engine().validator.validate(doc, leaked, [])))


class EngineBehaviourTests(unittest.TestCase):
    def test_strict_mode_raises_with_the_problems(self) -> None:
        doc = build([H("A"), Pg(sentences(3))])
        with mock.patch.object(ChunkValidator, "validate", return_value=["boom"]):
            with self.assertRaises(ChunkValidationError) as caught:
                engine(strict=True).run(doc, CTX)
            self.assertEqual(caught.exception.problems, ["boom"])
            lenient = engine(strict=False).run(doc, CTX)
            self.assertEqual(lenient.report.problems, ["boom"])

    def test_rejects_documents_it_cannot_chunk(self) -> None:
        doc = build([H("A"), Pg(sentences(3))])
        with self.assertRaises(ChunkingError):
            engine().run(dataclasses.replace(doc, source=None), CTX)
        with self.assertRaises(ChunkingError):
            engine().run(dataclasses.replace(doc, schema_version="1.0"), CTX)

    def test_intentionally_skipped_title_only_slide_is_not_a_coverage_problem(self) -> None:
        blocks = [H("Divider", page=1), Pg("tiny", page=1), H("Real", page=2), Pg(sentences(3), page=2)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=2))
        result = engine(strict=True).run(doc, CTX)

        self.assertEqual(result.report.skipped_slides, [1])
        self.assertEqual({c.slide_number for c in result.children}, {2})

    def test_empty_document_yields_empty_set(self) -> None:
        result = engine().run(build([]), CTX)

        self.assertIsInstance(result, ChunkSet)
        self.assertEqual((result.children, result.parents), ([], []))

    def test_components_are_replaceable(self) -> None:
        class CountsCalls(WordCounter):
            name = "custom"
            calls = 0

            def count(self, text: str) -> int:
                CountsCalls.calls += 1
                return super().count(text)

        eng = ChunkingEngine(SMALL, CountsCalls())
        child = eng.run(build([H("A"), Pg(sentences(3))]), CTX).children[0]

        self.assertGreater(CountsCalls.calls, 0)
        self.assertEqual(child.tokenizer, "custom")


class IngestionCompatibilityTests(unittest.TestCase):
    """Real documents through the real ingestion pipeline."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        ocr = fx.FakeOCR()
        self.pipeline = IngestionPipeline(
            pptx_reader=PptxReader(ocr_processor=ocr),  # type: ignore[arg-type]
            docx_reader=DocxReader(ocr_processor=ocr),  # type: ignore[arg-type]
        )
        self.engine = ChunkingEngine(tokenizer=WordCounter(), strict=True)

    def verify(self, document, unit: str, file_type: str):
        first = self.engine.run(document, CTX)
        second = self.engine.run(document, CTX)
        self.assertEqual(first, second)  # deterministic, field by field
        self.assertTrue(first.children)
        self.assertEqual(first.report.problems, [])
        ids = [c.chunk_id for c in [*first.children, *first.parents]]
        self.assertEqual(len(ids), len(set(ids)))
        for child in first.children:
            self.assertEqual((child.unit, child.file_type), (unit, file_type))
            json.dumps(child.chroma_metadata())
            self.assertEqual(child.doc_id, document.source.doc_id)
            self.assertEqual(child.sha256, document.source.sha256)
        return first

    def test_pdf(self) -> None:
        pages = [[("Chapter One", 24.0), ("Basics", 16.0), *pf.body()],
                 pf.body("More text on the second page of the document.")]
        doc = self.pipeline.ingest(pf.make_pdf(self.dir / "a.pdf", pages))
        result = self.verify(doc, "page", "pdf")

        self.assertTrue(result.children[0].citation_label.startswith("p. 1"))

    def test_docx(self) -> None:
        document = new_docx()
        document.add_heading("Notes", 1)
        document.add_paragraph("Body text of the notes.")
        document.add_paragraph("point", style="List Bullet")
        table = document.add_table(rows=2, cols=2)
        for r in range(2):
            for c in range(2):
                table.cell(r, c).text = f"r{r}c{c}"
        path = self.dir / "n.docx"
        document.save(str(path))
        result = self.verify(self.pipeline.ingest(path), "document", "docx")

        self.assertTrue(any(c.kind == "table" for c in result.children))
        self.assertTrue(all(c.page_number == 1 for c in result.children))

    def test_pptx_with_hidden_and_title_only_slides(self) -> None:
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "Lecture", [("Main point of the lecture", 0), ("A sub point", 1)])
        hidden = fx.add_bullet_slide(prs, "Hidden", [("Do not index this slide", 0)])
        hidden._element.set("show", "0")
        prs.slides.add_slide(prs.slide_layouts[fx.LAYOUT_TITLE_ONLY]).shapes.title.text = "Divider"
        fx.add_chart_slide(prs, "Results")
        slide_with_notes = fx.add_bullet_slide(prs, "Noted", [("Some bullet words here for the notes slide", 0)])
        slide_with_notes.notes_slide.notes_text_frame.text = "Say this out loud please"
        result = self.verify(self.pipeline.ingest(fx.save(prs, self.dir)), "slide", "pptx")

        slides = {c.slide_number for c in result.children}
        self.assertNotIn(2, slides)   # hidden
        self.assertNotIn(3, slides)   # title-only divider
        kinds = {c.kind for c in result.children}
        self.assertTrue({"chart", "notes", "text"} <= kinds)

    def test_sample_documents_from_the_repository(self) -> None:
        samples = sorted(Path("data/uploads").glob("*.pdf"))[:2]
        if not samples:
            self.skipTest("no sample PDFs available")
        for sample in samples:
            with self.subTest(sample=sample.name):
                self.verify(self.pipeline.ingest(sample), "page", "pdf")


if __name__ == "__main__":
    unittest.main()

"""The FINAL chunking decisions, one test per rule."""

from __future__ import annotations

import dataclasses
import unittest

from ai.chunking.config import ChunkConfig
from ai.chunking.engine import ChunkingEngine
from ai.chunking.models import ChunkContext
from ai.ingestion.models import Block, BlockType, PageContent, TableData
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
    words,
)


def engine(config=SMALL) -> ChunkingEngine:
    return ChunkingEngine(config, WordCounter())


class DefaultConfigTests(unittest.TestCase):
    def test_final_numbers(self) -> None:
        cfg = ChunkConfig()

        self.assertEqual((cfg.target_tokens, cfg.max_tokens, cfg.overlap_tokens), (400, 480, 60))
        self.assertEqual(cfg.table_max_tokens, 400)
        self.assertEqual(cfg.low_confidence_page, 0.6)
        self.assertEqual(cfg.ocr_min_confidence, 0.3)
        self.assertEqual(cfg.drop_below_page_confidence, 0.3)

    def test_context_has_no_include_hidden_switch(self) -> None:
        self.assertNotIn("include_hidden", {f.name for f in dataclasses.fields(ChunkContext)})


class OcrConfidenceTests(unittest.TestCase):
    def kinds(self, confidence: float):
        doc = build([H("F"), Pg(sentences(2)), OCR("recognised words from image", confidence)])
        return engine().run(doc, CTX)

    def test_below_0_3_is_not_indexed(self) -> None:
        result = self.kinds(0.29)

        self.assertEqual([c.kind for c in result.children], ["text"])
        self.assertEqual(result.report.dropped_blocks, 1)

    def test_between_0_3_and_0_6_is_indexed_and_flagged(self) -> None:
        for confidence in (0.3, 0.45, 0.59):
            with self.subTest(confidence=confidence):
                result = self.kinds(confidence)
                image = next(c for c in result.children if c.kind == "image_ocr")
                self.assertTrue(image.low_confidence)
                self.assertAlmostEqual(image.ocr_confidence, confidence)

    def test_0_6_and_above_is_not_flagged(self) -> None:
        image = next(c for c in self.kinds(0.6).children if c.kind == "image_ocr")

        self.assertFalse(image.low_confidence)

    def test_whole_page_ocr_thresholds(self) -> None:
        pages = [
            PageContent(page_number=1, ocr_applied=True, confidence=0.29),
            PageContent(page_number=2, ocr_applied=True, confidence=0.3),
            PageContent(page_number=3, ocr_applied=True, confidence=0.6),
        ]
        blocks = []
        for n in (1, 2, 3):
            blocks += [H(f"Page {n}", page=n), Pg(sentences(2, prefix=f"p{n}"), page=n)]
        result = engine().run(build(blocks, pages=pages), CTX)
        by_page = {c.page_start: c for c in result.children}

        self.assertNotIn(1, by_page)
        self.assertEqual(result.report.skipped_pages, [1])
        self.assertTrue(by_page[2].low_confidence)
        self.assertFalse(by_page[3].low_confidence)
        self.assertAlmostEqual(by_page[2].ocr_confidence, 0.3)

    def test_ocr_content_is_labelled(self) -> None:
        image = next(c for c in self.kinds(0.9).children if c.kind == "image_ocr")

        self.assertTrue(image.text.startswith("[Image text]"))
        self.assertIn("[Image text]", image.embedding_text)


class AtomicKindTests(unittest.TestCase):
    def test_chart_is_atomic_and_never_overlapped(self) -> None:
        blocks = [
            H("Results", page=1), Pg(sentences(6, per=9, prefix="a"), page=1),
            Block(BlockType.CHART, "Title: Scores\nSeries: A, B", 1),
            Pg(sentences(6, per=9, prefix="b"), page=1),
        ]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=1))
        children = engine().run(doc, CTX).children
        chart = next(c for c in children if c.kind == "chart")
        after = children[children.index(chart) + 1]

        self.assertEqual(chart.overlap_prefix, "")
        self.assertEqual(after.overlap_prefix, "")
        self.assertTrue(chart.text.startswith("[Chart]"))
        self.assertEqual(chart.block_types, ("chart",))

    def test_notes_are_atomic_and_never_overlapped(self) -> None:
        blocks = [
            H("S", page=1), Pg(sentences(6, per=9), page=1),
            Block(BlockType.NOTES, "short speaker note about caching policies", 1),
        ]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=1))
        notes = [c for c in engine().run(doc, CTX).children if c.kind == "notes"]

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].overlap_prefix, "")

    def test_atoms_are_split_only_when_they_exceed_the_hard_limit(self) -> None:
        small_note = "word " * 30           # < max_tokens (60): stays whole
        huge_note = sentences(20, per=8)    # 160 words: must be split
        for text, expected_parts in ((small_note, 1), (huge_note, None)):
            doc = build(
                [H("S", page=1), Block(BlockType.NOTES, text, 1)],
                unit="slide", file_type="pptx", metadata=slide_meta(count=1),
            )
            notes = [c for c in engine().run(doc, CTX).children if c.kind == "notes"]
            if expected_parts == 1:
                self.assertEqual(len(notes), 1)
            else:
                self.assertGreater(len(notes), 1)
            for note in notes:
                self.assertLessEqual(note.token_count, SMALL.max_tokens)

    def test_heading_never_becomes_its_own_chunk(self) -> None:
        doc = build([H("Only heading"), H("Another", 2)])

        self.assertEqual(engine().run(doc, CTX).children, [])


class SlideRuleTests(unittest.TestCase):
    def test_hidden_slides_are_always_excluded(self) -> None:
        blocks = [H("Shown", page=1), Pg(sentences(3), page=1),
                  H("Hidden", page=2), Pg(sentences(3, prefix="h"), page=2)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(2, count=2))
        result = engine().run(doc, CTX)

        self.assertEqual({c.slide_number for c in result.children}, {1})
        self.assertEqual(result.report.hidden_slides_excluded, [2])
        self.assertFalse(any("Hidden" in c.text or "Hidden" in c.embedding_text for c in result.children))

    def test_title_only_slide_is_not_indexed_but_its_notes_are(self) -> None:
        blocks = [H("Divider", page=1),
                  Block(BlockType.NOTES, "talk about the next section briefly", 1),
                  H("Real", page=2), Pg(sentences(3), page=2)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=2))
        result = engine().run(doc, CTX)

        self.assertEqual({(c.slide_number, c.kind) for c in result.children},
                         {(1, "notes"), (2, "text")})

    def test_no_chunk_or_parent_spans_slides(self) -> None:
        blocks = []
        for n in range(1, 6):
            blocks += [H(f"Slide {n}", page=n), Pg(words(4, f"x{n}_"), page=n)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=5))
        result = engine().run(doc, CTX)

        for chunk in [*result.children, *result.parents]:
            self.assertEqual(chunk.page_start, chunk.page_end)

    def test_small_slides_are_never_merged_together(self) -> None:
        blocks = [H("A", page=1), Pg("tiny a text here.", page=1),
                  H("B", page=2), Pg("tiny b text here.", page=2)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=2))

        self.assertEqual([c.slide_number for c in engine().run(doc, CTX).children], [1, 2])


class TableRuleTests(unittest.TestCase):
    @staticmethod
    def doc(rows):
        table = TableData(page_number=1, index=0, rows=rows)
        blocks = [H("Data"), Pg("Table 1 lists values."), Block(BlockType.TABLE, "x", 1, ref_index=0)]
        return build(blocks, pages=[PageContent(page_number=1, tables=[table])])

    def test_every_split_part_repeats_header_keeps_context_and_citation(self) -> None:
        rows = [["Name", "Value"]] + [[f"row{i}", str(i)] for i in range(40)]
        parts = [c for c in engine().run(self.doc(rows), CTX).children if c.kind == "table"]

        self.assertGreater(len(parts), 1)
        self.assertEqual({p.citation_label for p in parts}, {"p. 1 > Data"})
        for part in parts:
            self.assertTrue(part.text.startswith("| Name | Value |"))
            self.assertEqual(part.table_parts, len(parts))
            self.assertEqual(part.block_types, ("table",))
        self.assertIn("Context: Table 1 lists values.", parts[0].embedding_text)

    def test_table_at_the_limit_stays_whole(self) -> None:
        rows = [["A", "B"], ["1", "2"], ["3", "4"]]
        parts = [c for c in engine().run(self.doc(rows), CTX).children if c.kind == "table"]

        self.assertEqual(len(parts), 1)
        self.assertIsNone(parts[0].table_parts)


if __name__ == "__main__":
    unittest.main()

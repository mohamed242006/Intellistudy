"""Chunking: edge cases, failure cases, hard-limit guarantees and seeded property tests.

Complements test_chunker.py / test_chunk_rules.py (rule-by-rule) with adversarial input.
"""

from __future__ import annotations

import collections
import re
import unittest

from ai.chunking import ApproxTokenCounter, ChunkConfig, ChunkContext, ChunkingEngine
from ai.ingestion.models import Block, BlockType, PageContent, TableData
from tests.chunk_fixtures import (
    CTX,
    LI,
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
from tests.random_docs import random_document

DEFAULT = ChunkConfig()  # the real 400 / 480 / 60 configuration
WORD = re.compile(r"\w+")


def engine(config: ChunkConfig = DEFAULT, counter=None, **kwargs) -> ChunkingEngine:
    return ChunkingEngine(config, counter or WordCounter(), **kwargs)


def table_doc(rows, *, intro: str | None = "Table 1 lists values."):
    table = TableData(page_number=1, index=0, rows=rows)
    blocks = [H("Data")]
    if intro:
        blocks.append(Pg(intro))
    blocks.append(Block(BlockType.TABLE, "x", 1, ref_index=0))
    return build(blocks, pages=[PageContent(page_number=1, tables=[table])])


class EmptyAndTrivialTests(unittest.TestCase):
    def test_document_without_blocks(self) -> None:
        result = engine().run(build([]), CTX)

        self.assertEqual((result.children, result.parents), ([], []))
        self.assertEqual(result.report.problems, [])

    def test_only_headings_or_only_whitespace(self) -> None:
        for blocks in ([H("A"), H("B", 2)], [Pg("   \n\t  ")], [H("A"), Pg("")], [Pg("\u00a0\u200b")]):
            with self.subTest(blocks=[b.text for b in blocks]):
                self.assertEqual(engine(strict=True).run(build(blocks), CTX).children, [])

    def test_single_character_and_single_word_documents(self) -> None:
        for text in ("x", "word", "7"):
            with self.subTest(text=text):
                chunks = engine(strict=True).chunk(build([Pg(text)]), CTX)
                self.assertEqual([c.text for c in chunks], [text])

    def test_content_before_the_first_heading_has_an_empty_path(self) -> None:
        chunks = engine().chunk(build([Pg(sentences(2)), H("A"), Pg(sentences(2, prefix="b"))]), CTX)

        self.assertEqual([c.heading_path for c in chunks][0], ())
        self.assertEqual(chunks[0].citation_label, "p. 1")

    def test_empty_sections_between_populated_ones(self) -> None:
        blocks = [H("A", 1), H("B", 2), H("C", 3), Pg(sentences(2)),
                  H("D", 1), H("E", 2), Pg(sentences(2, prefix="e"))]
        chunks = engine(strict=True).chunk(build(blocks), CTX)

        self.assertEqual([c.heading_path for c in chunks], [("A", "B", "C"), ("D", "E")])


class HugeInputTests(unittest.TestCase):
    def test_one_enormous_sentence_without_punctuation(self) -> None:
        text = " ".join(f"w{i}" for i in range(20_000))
        chunks = engine(strict=True).chunk(build([H("A"), Pg(text)]), CTX)

        self.assertGreater(len(chunks), 40)
        self.assertLessEqual(max(c.token_count for c in chunks), DEFAULT.max_tokens)
        self.assertEqual(" ".join(c.text for c in chunks).split(), text.split())  # nothing lost

    def test_one_huge_section_of_many_paragraphs(self) -> None:
        blocks = [H("Big")] + [Pg(sentences(3, per=10, prefix=f"p{i}_")) for i in range(2000)]
        result = engine(strict=True).run(build(blocks), CTX)

        self.assertEqual(result.report.problems, [])
        self.assertTrue(all(c.token_count <= DEFAULT.max_tokens for c in result.children))
        self.assertTrue(all(p.token_count <= DEFAULT.parent_max_tokens + DEFAULT.max_tokens
                            for p in result.parents))
        self.assertGreater(len(result.parents), 10)

    def test_many_tiny_sections(self) -> None:
        blocks = []
        for i in range(1500):
            blocks += [H(f"S{i}"), Pg(f"tiny content {i} here now.")]
        result = engine(strict=True).run(build(blocks), CTX)

        self.assertEqual(len(result.children), 1500)  # top-level siblings are never merged
        self.assertEqual(len({c.chunk_id for c in result.children}), 1500)

    def test_thousand_row_table_keeps_every_row_exactly_once_in_order(self) -> None:
        rows = [["id", "name", "value"]] + [[f"id{i}", f"name{i}", f"v{i}"] for i in range(1000)]
        parts = [c for c in engine(strict=True).chunk(table_doc(rows), CTX) if c.kind == "table"]

        seen = [m for c in parts for m in re.findall(r"\bid(\d+)\b", c.text)]
        self.assertEqual(seen, [str(i) for i in range(1000)])
        for number, part in enumerate(parts, start=1):
            self.assertEqual((part.table_part, part.table_parts), (number, len(parts)))
            self.assertTrue(part.text.startswith("| id | name | value |"))


class HardLimitRegressionTests(unittest.TestCase):
    """REG-01/02/03: no chunk may exceed max_tokens, whatever single atom is oversize."""

    def test_single_list_item_longer_than_the_limit_is_split(self) -> None:
        text = " ".join(sentences(1, per=700).split())
        chunks = engine(strict=True).chunk(build([H("A"), LI(text)]), CTX)

        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(max(c.token_count for c in chunks), DEFAULT.max_tokens)
        self.assertEqual(" ".join(c.text for c in chunks).replace("- ", "").split(), text.split())

    def test_single_table_row_longer_than_the_limit_is_split_by_cells(self) -> None:
        rows = [["Name", "Notes"], ["row-label", " ".join(f"n{i}" for i in range(700))]]
        parts = [c for c in engine(strict=True).chunk(table_doc(rows), CTX) if c.kind == "table"]

        self.assertLessEqual(max(c.token_count for c in parts), DEFAULT.max_tokens)
        joined = " ".join(c.text for c in parts)
        for i in range(700):
            self.assertEqual(len(re.findall(rf"\bn{i}\b", joined)), 1)

    def test_table_with_many_columns_in_one_row(self) -> None:
        header = [f"H{c}" for c in range(300)]
        row = [f"cell{c} " + "x " * 5 for c in range(300)]
        parts = [c for c in engine(strict=True).chunk(table_doc([header, row]), CTX) if c.kind == "table"]

        self.assertLessEqual(max(c.token_count for c in parts), DEFAULT.max_tokens)
        joined = " ".join(c.text for c in parts)
        self.assertTrue(all(f"cell{c} " in joined for c in range(300)))

    def test_chart_longer_than_the_limit_is_split(self) -> None:
        blocks = [H("S", page=1), Block(BlockType.CHART, "Series: " + " ".join(f"s{i}" for i in range(900)), 1)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=1))
        chunks = engine(strict=True).chunk(doc, CTX)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.kind == "chart" for c in chunks))
        self.assertLessEqual(max(c.token_count for c in chunks), DEFAULT.max_tokens)

    def test_pathologically_long_heading_does_not_blow_the_limit(self) -> None:
        title = " ".join(f"title{i}" for i in range(900))
        chunks = engine(strict=True).chunk(build([H(title), Pg(sentences(4))]), CTX)

        self.assertTrue(chunks)
        self.assertLessEqual(max(c.token_count for c in chunks), DEFAULT.max_tokens)
        self.assertEqual(chunks[0].heading_path, (title,))  # metadata keeps the full title

    def test_long_deep_heading_path_is_bounded(self) -> None:
        blocks = []
        for level in range(1, 7):
            blocks.append(H(" ".join(f"L{level}w{i}" for i in range(120)), level))
        blocks.append(Pg(sentences(4)))
        chunks = engine(strict=True).chunk(build(blocks), CTX)

        self.assertLessEqual(max(c.token_count for c in chunks), DEFAULT.max_tokens)

    def test_works_with_a_character_based_counter_too(self) -> None:
        chunks = engine(counter=ApproxTokenCounter(), strict=True).chunk(
            build([H("A"), Pg(sentences(400, per=12))]), CTX)

        self.assertLessEqual(max(c.token_count for c in chunks), DEFAULT.max_tokens)


class NestedHeadingTests(unittest.TestCase):
    def test_six_levels_produce_exact_paths(self) -> None:
        blocks = []
        for level in range(1, 7):
            blocks += [H(f"L{level}", level), Pg(sentences(12, per=10, prefix=f"l{level}_"))]
        by_path = {c.heading_path for c in engine(SMALL, strict=True).chunk(build(blocks), CTX)}

        for level in range(1, 7):
            self.assertIn(tuple(f"L{n}" for n in range(1, level + 1)), by_path)

    def test_sibling_after_deeper_section_pops_the_stack(self) -> None:
        blocks = [H("A", 1), H("A1", 2), H("A1a", 3), Pg(sentences(12, per=10)), H("A2", 2),
                  Pg(sentences(12, per=10, prefix="x")), H("B", 1), Pg(sentences(12, per=10, prefix="y"))]
        paths = [c.heading_path for c in engine(SMALL, strict=True).chunk(build(blocks), CTX)]

        self.assertIn(("A", "A1", "A1a"), paths)
        self.assertIn(("A", "A2"), paths)
        self.assertIn(("B",), paths)
        self.assertNotIn(("A", "A1", "A2"), paths)

    def test_repeated_heading_titles_stay_distinct_sections(self) -> None:
        blocks = [H("Summary"), Pg(sentences(12, per=10)), H("Summary"), Pg(sentences(12, per=10, prefix="b"))]
        chunks = engine(SMALL, strict=True).chunk(build(blocks), CTX)

        self.assertEqual(len({c.chunk_id for c in chunks}), len(chunks))
        self.assertTrue(all(c.heading_path == ("Summary",) for c in chunks))

    def test_level_zero_title_and_skipped_levels(self) -> None:
        blocks = [H("Doc title", 0), H("Deep", 4), Pg(sentences(12, per=10)), H("Back", 1),
                  Pg(sentences(12, per=10, prefix="b"))]
        paths = {c.heading_path for c in engine(SMALL, strict=True).chunk(build(blocks), CTX)}

        self.assertIn(("Doc title", "Deep"), paths)
        self.assertIn(("Doc title", "Back"), paths)  # level 0 is the root above every heading 1


class TableEdgeTests(unittest.TestCase):
    def chunks(self, rows, **kw):
        return [c for c in engine(strict=True).chunk(table_doc(rows, **kw), CTX) if c.kind == "table"]

    def test_header_only_single_column_and_single_row_tables(self) -> None:
        for rows in ([["A", "B"]], [["A"], ["1"], ["2"]], [["only"]]):
            with self.subTest(rows=rows):
                parts = self.chunks(rows)
                self.assertEqual(len(parts), 1)
                self.assertTrue(parts[0].text)

    def test_ragged_and_empty_cells(self) -> None:
        parts = self.chunks([["a", "b", "c"], ["1"], ["1", "2", "3", "4"], ["", "", ""]])

        self.assertEqual(len(parts), 1)
        self.assertIn("| 1 |", parts[0].text)

    def test_pipes_and_newlines_in_cells_do_not_break_the_grid(self) -> None:
        parts = self.chunks([["expr", "meaning"], ["a|b", "line1\nline2"]])
        row = parts[0].text.splitlines()[-1]

        self.assertEqual(row.count(" | "), 1)  # two cells, one separator
        self.assertIn(r"a\|b", row)  # escaped, never rewritten to a different character (E2E-02)

    def test_duplicate_and_blank_header_names(self) -> None:
        parts = self.chunks([["x", "x", ""], ["1", "2", "3"]])

        self.assertIn("Column 3: 3", parts[0].embedding_text)

    def test_unicode_cells(self) -> None:
        parts = self.chunks([["اسم", "值"], ["محمد", "日本語 😀"]])

        self.assertIn("日本語 😀", parts[0].text)

    def test_missing_table_object_falls_back_to_reader_text(self) -> None:
        doc = build([H("T"), Block(BlockType.TABLE, "Name: alpha\nValue: 1", 1, ref_index=7)])
        chunks = engine(strict=True).chunk(doc, CTX)

        self.assertEqual([c.kind for c in chunks], ["table"])
        self.assertIn("Name: alpha", chunks[0].text)

    def test_context_only_when_the_preceding_paragraph_is_short(self) -> None:
        short = [c for c in engine().chunk(table_doc([["A", "B"], ["1", "2"]], intro="Short intro."), CTX)
                 if c.kind == "table"][0]
        long_intro = " ".join(f"w{i}" for i in range(300))
        long = [c for c in engine().chunk(table_doc([["A", "B"], ["1", "2"]], intro=long_intro), CTX)
                if c.kind == "table"][0]
        none = [c for c in engine().chunk(table_doc([["A", "B"], ["1", "2"]], intro=None), CTX)
                if c.kind == "table"][0]

        self.assertIn("Context: Short intro.", short.embedding_text)
        self.assertNotIn("Context:", long.embedding_text)
        self.assertNotIn("Context:", none.embedding_text)


class OverlapCorrectnessTests(unittest.TestCase):
    def doc(self):
        return build([H("Long")] + [Pg(sentences(5, per=12, prefix=f"p{i}_")) for i in range(12)])

    def test_overlap_is_whole_sentences_from_the_previous_chunk_within_budget(self) -> None:
        chunks = engine().chunk(self.doc(), CTX)
        overlapping = [c for c in chunks if c.overlap_prefix]

        self.assertTrue(overlapping)
        for chunk in overlapping:
            previous = chunks[chunk.ordinal - 1]
            self.assertLessEqual(len(chunk.overlap_prefix.split()), DEFAULT.overlap_tokens)
            self.assertTrue(previous.text.rstrip().endswith(chunk.overlap_prefix.rstrip()))
            self.assertTrue(chunk.overlap_prefix.rstrip().endswith("."))  # never cut mid-sentence

    def test_overlap_text_never_appears_in_own_text_and_ids_ignore_it(self) -> None:
        with_overlap = engine().chunk(self.doc(), CTX)
        without = engine(ChunkConfig(overlap_tokens=0)).chunk(self.doc(), CTX)

        self.assertEqual([c.chunk_id for c in with_overlap], [c.chunk_id for c in without])
        self.assertTrue(all(c.overlap_prefix == "" for c in without))
        for chunk in with_overlap:
            if chunk.overlap_prefix:
                self.assertNotIn(chunk.overlap_prefix, chunk.text)

    def test_no_overlap_at_section_table_slide_boundaries(self) -> None:
        blocks = [H("A"), Pg(sentences(40, per=10)), H("B"), Pg(sentences(40, per=10, prefix="b"))]
        chunks = engine().chunk(build(blocks), CTX)
        firsts = {c.heading_path: c for c in reversed(chunks)}

        self.assertEqual(firsts[("B",)].overlap_prefix, "")

    def test_overlap_larger_than_one_sentence_budget_is_empty_not_truncated(self) -> None:
        # every sentence is 80 tokens > overlap budget 60: nothing may be cut mid-sentence
        doc = build([H("A")] + [Pg(words(80, f"p{i}_")) for i in range(12)])
        chunks = engine().chunk(doc, CTX)

        self.assertTrue(all(c.overlap_prefix == "" for c in chunks))

    def test_overlap_is_dropped_when_it_would_break_the_hard_limit(self) -> None:
        cfg = ChunkConfig(target_tokens=100, max_tokens=110, min_tokens=20, overlap_tokens=60,
                          parent_max_tokens=500, prefix_max_tokens=20)
        doc = build([H("A")] + [Pg(sentences(8, per=5, prefix=f"p{i}_")) for i in range(30)])
        chunks = engine(cfg).chunk(doc, CTX)

        self.assertLessEqual(max(c.token_count for c in chunks), cfg.max_tokens)


class OcrChartNotesHiddenTests(unittest.TestCase):
    def test_ocr_confidence_boundaries_are_exact(self) -> None:
        cases = {0.2999: False, 0.3: True, 0.5999: True, 0.6: True}  # value: indexed?
        for confidence, indexed in cases.items():
            with self.subTest(confidence=confidence):
                chunks = engine().chunk(build([H("F"), OCR("words from the image here", confidence)]), CTX)
                self.assertEqual(any(c.kind == "image_ocr" for c in chunks), indexed)

    def test_missing_ocr_confidence_is_not_treated_as_garbage(self) -> None:
        chunks = engine().chunk(build([H("F"), OCR("words from the image here", None)]), CTX)

        self.assertEqual([c.kind for c in chunks], ["image_ocr"])
        self.assertIsNone(chunks[0].ocr_confidence)

    def test_hidden_slide_content_never_leaks_into_neighbours_or_parents(self) -> None:
        blocks = [H("One", page=1), Pg("shown content alpha beta gamma delta epsilon.", page=1),
                  H("Two", page=2), Pg("SECRETWORD hidden content right here now.", page=2),
                  Block(BlockType.NOTES, "SECRETNOTE hidden notes", 2),
                  H("Three", page=3), Pg("shown content zeta eta theta iota kappa.", page=3)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(2, count=3))
        result = engine(strict=True).run(doc, CTX)

        blob = " ".join(c.text + c.embedding_text for c in result.children) + " ".join(p.text for p in result.parents)
        self.assertNotIn("SECRET", blob)
        self.assertEqual({c.slide_number for c in result.children}, {1, 3})

    def test_slide_with_everything_produces_separate_atomic_chunks(self) -> None:
        table = TableData(page_number=1, index=0, rows=[["A", "B"], ["1", "2"]])
        blocks = [H("Rich", page=1), Pg(sentences(3), page=1), LI("bullet point text here", page=1),
                  Block(BlockType.CHART, "Title: T", 1), Block(BlockType.TABLE, "x", 1, ref_index=0),
                  OCR("image words here now", 0.9), Block(BlockType.NOTES, "speaker words here", 1)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=1),
                    pages=[PageContent(page_number=1, tables=[table])])
        chunks = engine(strict=True).chunk(doc, CTX)

        self.assertEqual({c.kind for c in chunks}, {"text", "chart", "table", "image_ocr", "notes"})
        self.assertTrue(all(c.page_start == c.page_end == 1 for c in chunks))
        for atom_kind in ("chart", "table", "notes"):
            self.assertEqual(sum(c.kind == atom_kind for c in chunks), 1)


class ConfigValidationTests(unittest.TestCase):
    def test_invalid_configurations_are_rejected(self) -> None:
        for kwargs in ({"target_tokens": 0}, {"min_tokens": 500}, {"max_tokens": 100},
                       {"overlap_tokens": 400}, {"overlap_tokens": -1}, {"parent_max_tokens": 100}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ChunkConfig(**kwargs)

    def test_chunking_context_is_required_to_be_complete_by_the_indexer_not_the_chunker(self) -> None:
        chunks = engine().chunk(build([H("A"), Pg(sentences(2))]),
                                ChunkContext(user_id="", course_id="", document_uid="d"))

        self.assertEqual(chunks[0].user_id, "")  # chunker is pure; scope checks live in the stores


class PropertyTests(unittest.TestCase):
    """60 seeded random documents x 3 units: every invariant must hold for all of them."""

    SEEDS = range(20)

    def run_all(self):
        for unit in ("page", "slide", "document"):
            for seed in self.SEEDS:
                yield unit, seed, random_document(seed, unit=unit)

    def test_strict_validation_determinism_and_token_limits(self) -> None:
        eng = engine(strict=True)
        for unit, seed, rd in self.run_all():
            with self.subTest(unit=unit, seed=seed):
                first = eng.run(rd.document, CTX)
                second = eng.run(rd.document, CTX)
                self.assertEqual(first, second)
                self.assertEqual(first.report.problems, [])
                self.assertLessEqual(max((c.token_count for c in first.children), default=0),
                                     DEFAULT.max_tokens)
                ids = [c.chunk_id for c in first.children] + [p.chunk_id for p in first.parents]
                self.assertEqual(len(ids), len(set(ids)))

    def test_no_word_is_lost_or_duplicated(self) -> None:
        eng = engine(strict=True)
        for unit, seed, rd in self.run_all():
            with self.subTest(unit=unit, seed=seed):
                result = eng.run(rd.document, CTX)
                skipped = set(result.report.skipped_slides) | set(result.report.hidden_slides_excluded)
                dropped_pages = set(result.report.skipped_pages)
                expected: collections.Counter[str] = collections.Counter()
                for block in rd.document.blocks:
                    if block.page_number in skipped | dropped_pages and block.type is not BlockType.NOTES:
                        continue
                    if block.page_number in result.report.hidden_slides_excluded:
                        continue
                    if block.type in (BlockType.PARAGRAPH, BlockType.LIST_ITEM, BlockType.IMAGE_OCR,
                                      BlockType.CHART, BlockType.NOTES):
                        expected.update(w for w in WORD.findall(block.text) if "_" in w)
                actual: collections.Counter[str] = collections.Counter(
                    w for c in result.children for w in WORD.findall(c.text) if "_" in w)
                # a title-only slide drops its body but keeps its notes
                self.assertEqual(+(expected - actual), collections.Counter(), "words lost")
                self.assertEqual(+(actual - expected), collections.Counter(), "words duplicated")

    def test_every_table_row_appears_exactly_once(self) -> None:
        eng = engine(strict=True)
        for unit, seed, rd in self.run_all():
            with self.subTest(unit=unit, seed=seed):
                result = eng.run(rd.document, CTX)
                hidden = set(result.report.hidden_slides_excluded) | set(result.report.skipped_slides)
                want: collections.Counter[str] = collections.Counter()
                for page in rd.document.pages:
                    if page.page_number in hidden:
                        continue
                    for table in page.tables:
                        want.update(c for row in table.rows[1:] for c in row[:1])
                got: collections.Counter[str] = collections.Counter(
                    w for c in result.children if c.kind == "table"
                    for w in re.findall(r"\bt\d+r\d+c0\b", c.text))
                self.assertEqual(got, want)

    def test_parents_partition_children_and_concatenate_their_text(self) -> None:
        eng = engine(strict=True)
        for unit, seed, rd in self.run_all():
            with self.subTest(unit=unit, seed=seed):
                result = eng.run(rd.document, CTX)
                owned = [cid for p in result.parents for cid in p.child_ids]
                self.assertEqual(sorted(owned), sorted(c.chunk_id for c in result.children))
                for parent in result.parents:
                    self.assertEqual(parent.text, "\n\n".join(c.text for c in result.children_of(parent)))
                    self.assertTrue(all(c.parent_id == parent.chunk_id for c in result.children_of(parent)))

    def test_slides_never_mix_and_hidden_slides_never_appear(self) -> None:
        eng = engine(strict=True)
        for seed in self.SEEDS:
            with self.subTest(seed=seed):
                rd = random_document(seed, unit="slide")
                result = eng.run(rd.document, CTX)
                for chunk in [*result.children, *result.parents]:
                    self.assertEqual(chunk.page_start, chunk.page_end)
                    self.assertNotIn(chunk.page_start, rd.hidden_slides)

    def test_overlap_only_between_neighbouring_text_chunks(self) -> None:
        eng = engine(strict=True)
        for unit, seed, rd in self.run_all():
            with self.subTest(unit=unit, seed=seed):
                children = eng.run(rd.document, CTX).children
                for chunk in children:
                    if chunk.overlap_prefix:
                        self.assertEqual(chunk.kind, "text")
                        previous = children[chunk.ordinal - 1]
                        self.assertEqual(previous.kind, "text")
                        shorter = min(len(previous.heading_path), len(chunk.heading_path))
                        self.assertEqual(previous.heading_path[:shorter], chunk.heading_path[:shorter])


if __name__ == "__main__":
    unittest.main()

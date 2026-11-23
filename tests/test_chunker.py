"""Engine behaviour tests: sectioning, packing, overlap, tables, slides, OCR, identity.

Rule-by-rule tests of the final decisions live in test_chunk_rules.py; parents in
test_chunk_parents.py; indexing in test_chunk_indexing.py.
"""

from __future__ import annotations

import unittest

from ai.chunking.config import ChunkConfig, collection_name
from ai.chunking.engine import ChunkingEngine
from ai.ingestion.models import Block, BlockType, Document, PageContent, TableData
from tests.chunk_fixtures import (
    CTX,
    LI,
    SMALL,
    H,
    Pg,
    WordCounter,
    build,
    sentences,
    words,
)


def chunker(config: ChunkConfig = SMALL) -> ChunkingEngine:
    return ChunkingEngine(config, WordCounter())


def check_invariants(engine: ChunkingEngine, document, ctx, chunks) -> list[str]:
    return engine.validator.validate(document, chunks, ctx=ctx)


class SectioningTests(unittest.TestCase):
    def test_chunks_do_not_cross_sections_and_carry_heading_path(self) -> None:
        doc = build([
            H("Caching"), Pg(sentences(3)),
            H("LRU", 2), Pg(sentences(3, prefix="t")),
            H("Networking"), Pg(sentences(3, prefix="u")),
        ])
        chunks = chunker().chunk(doc, CTX)

        paths = [c.heading_path for c in chunks]
        self.assertIn(("Caching", "LRU"), paths)
        self.assertIn(("Networking",), paths)
        self.assertEqual(check_invariants(chunker(), doc, CTX, chunks), [])
        networking = next(c for c in chunks if c.heading_path == ("Networking",))
        self.assertNotIn("s0_", networking.text)

    def test_embedding_text_carries_heading_context_but_text_does_not(self) -> None:
        doc = build([H("Caching"), H("LRU", 2), Pg(sentences(2))])
        chunk = chunker().chunk(doc, CTX)[0]

        self.assertTrue(chunk.embedding_text.startswith("Caching > LRU\n"))
        self.assertFalse(chunk.text.startswith("Caching"))
        self.assertEqual(chunk.citation_label, "p. 1 > Caching > LRU")

    def test_headings_alone_produce_no_chunks_and_are_never_last(self) -> None:
        doc = build([H("Empty"), H("Also empty", 2), Pg(sentences(2))])
        chunks = chunker().chunk(doc, CTX)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].heading_path, ("Empty", "Also empty"))


class PackingTests(unittest.TestCase):
    def test_long_section_is_packed_to_target(self) -> None:
        doc = build([H("Long")] + [Pg(sentences(1, per=15, prefix=f"p{i}")) for i in range(10)])
        chunks = chunker().chunk(doc, CTX)

        self.assertGreater(len(chunks), 2)
        for c in chunks:
            self.assertLessEqual(c.token_count, SMALL.max_tokens)
        self.assertEqual(check_invariants(chunker(), doc, CTX, chunks), [])

    def test_oversize_paragraph_is_split_at_sentences(self) -> None:
        doc = build([H("Big"), Pg(sentences(20, per=8))])  # 160 words, one paragraph
        chunks = chunker().chunk(doc, CTX)

        self.assertGreater(len(chunks), 3)
        for c in chunks:
            self.assertLessEqual(c.token_count, SMALL.max_tokens)
            self.assertTrue(c.text.rstrip().endswith("."))  # never cut mid-sentence

    def test_list_stays_together_and_splits_only_between_items(self) -> None:
        items = [LI(words(9, f"i{n}_"), marker=f"{n + 1}.") for n in range(12)]
        doc = build([H("Steps"), Pg("The steps are:")] + items)
        chunks = chunker().chunk(doc, CTX)

        joined = "\n".join(c.text for c in chunks)
        for n in range(12):
            self.assertEqual(joined.count(f"{n + 1}. i{n}_0"), 1)
        first = chunks[0].text
        self.assertTrue(first.startswith("The steps are:\n1. "))  # lead paragraph kept with list

    def test_small_neighbouring_sections_are_merged(self) -> None:
        doc = build([
            H("Parent"), Pg("Short intro sentence here."),
            H("Child", 2), Pg("Another short child paragraph."),
        ])
        chunks = chunker().chunk(doc, CTX)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].heading_path, ("Parent",))
        self.assertEqual(chunks[0].section_titles, ("Parent", "Child"))

    def test_merge_does_not_cross_unrelated_sections(self) -> None:
        doc = build([
            H("A"), Pg("tiny a one two three four five six."),
            H("B"), Pg("tiny b one two three four five six."),
        ])
        chunks = chunker().chunk(doc, CTX)

        self.assertEqual([c.heading_path for c in chunks], [("A",), ("B",)])


class OverlapTests(unittest.TestCase):
    def test_overlap_between_consecutive_chunks_of_one_section(self) -> None:
        doc = build([H("Long")] + [Pg(sentences(3, per=5, prefix=f"p{i}_")) for i in range(6)])
        chunks = chunker().chunk(doc, CTX)

        self.assertEqual(chunks[0].overlap_prefix, "")
        second = chunks[1]
        self.assertTrue(second.overlap_prefix)
        self.assertLessEqual(len(second.overlap_prefix.split()), SMALL.overlap_tokens)
        self.assertIn(second.overlap_prefix, chunks[0].text)
        self.assertIn(second.overlap_prefix, second.embedding_text)
        self.assertNotIn(second.overlap_prefix, second.text)  # own text is overlap-free

    def test_no_overlap_across_sections(self) -> None:
        doc = build([
            H("A"), Pg(sentences(6, per=9, prefix="a")),
            H("B"), Pg(sentences(6, per=9, prefix="b")),
        ])
        chunks = chunker().chunk(doc, CTX)
        first_b = next(c for c in chunks if c.heading_path == ("B",))

        self.assertEqual(first_b.overlap_prefix, "")

    def test_no_overlap_into_or_out_of_tables(self) -> None:
        rows = [["Name", "Value"], ["a", "1"], ["b", "2"]]
        table = TableData(page_number=1, index=0, rows=rows)
        blocks = [H("T"), Pg(sentences(6, per=9)), Block(BlockType.TABLE, "x", 1, ref_index=0),
                  Pg(sentences(6, per=9, prefix="z"))]
        pages = [PageContent(page_number=1, tables=[table])]
        doc = build(blocks, pages=pages)
        chunks = chunker().chunk(doc, CTX)

        table_chunk = next(c for c in chunks if c.kind == "table")
        after = chunks[chunks.index(table_chunk) + 1]
        self.assertEqual(table_chunk.overlap_prefix, "")
        self.assertEqual(after.overlap_prefix, "")


class TableTests(unittest.TestCase):
    @staticmethod
    def doc_with_table(rows: list[list[str]], intro: str = "Table 2 compares caches.") -> Document:
        table = TableData(page_number=1, index=0, rows=rows)
        blocks = [H("Results"), Pg(intro), Block(BlockType.TABLE, "ignored", 1, ref_index=0)]
        return build(blocks, pages=[PageContent(page_number=1, tables=[table])])

    def test_small_table_is_one_atomic_chunk(self) -> None:
        doc = self.doc_with_table([["Cache", "Hit"], ["L1", "95"], ["L2", "80"]])
        chunks = chunker().chunk(doc, CTX)
        table = next(c for c in chunks if c.kind == "table")

        self.assertEqual((table.table_part, table.table_parts), (None, None))
        self.assertIn("| Cache | Hit |", table.text)
        self.assertIn("Cache: L1\nHit: 95", table.embedding_text)
        self.assertIn("Context: Table 2 compares caches.", table.embedding_text)
        self.assertTrue(table.has_table)
        self.assertEqual(table.table_index, 0)

    def test_large_table_splits_by_rows_with_header_repeated(self) -> None:
        rows = [["Name", "Value", "Note"]] + [[f"row{i}", str(i), "n"] for i in range(30)]
        doc = self.doc_with_table(rows)
        chunks = [c for c in chunker().chunk(doc, CTX) if c.kind == "table"]

        self.assertGreater(len(chunks), 1)
        seen: list[str] = []
        for number, c in enumerate(chunks, start=1):
            self.assertEqual((c.table_part, c.table_parts), (number, len(chunks)))
            self.assertTrue(c.text.startswith("| Name | Value | Note |"))
            self.assertLessEqual(c.token_count, SMALL.max_tokens)
            seen += [line.split("|")[1].strip() for line in c.text.splitlines()[2:]]
        self.assertEqual(seen, [f"row{i}" for i in range(30)])  # no row lost, split or repeated

    def test_table_is_never_merged_with_text(self) -> None:
        doc = self.doc_with_table([["A", "B"], ["1", "2"]])
        chunks = chunker().chunk(doc, CTX)

        self.assertEqual(sorted(c.kind for c in chunks), ["table", "text"])


class SlideTests(unittest.TestCase):
    @staticmethod
    def slide_doc(include_hidden_meta: bool = True):
        blocks = [
            H("Intro", page=1), Pg("Welcome to the course.", page=1),
            H("Divider", page=2),
            H("Caching", page=3), LI("LRU evicts oldest entries first", page=3),
            LI("LFU evicts least used entries", page=3),
            Block(BlockType.NOTES, "Remember to demo the cache simulator.", 3),
            H("Secret", page=4), Pg("Hidden material about grading policy.", page=4),
        ]
        slides = [
            {"slide_number": 1, "title": "Intro", "has_notes": False, "hidden": False},
            {"slide_number": 2, "title": "Divider", "has_notes": False, "hidden": False},
            {"slide_number": 3, "title": "Caching", "has_notes": True, "hidden": False},
            {"slide_number": 4, "title": "Secret", "has_notes": False, "hidden": include_hidden_meta},
        ]
        return build(blocks, unit="slide", file_type="pptx", metadata={"slides": slides}, title="CS101")

    def test_chunks_never_cross_slides_and_use_slide_context(self) -> None:
        doc = self.slide_doc()
        chunks = chunker().chunk(doc, CTX)

        self.assertEqual(check_invariants(chunker(), doc, CTX, chunks), [])
        for c in chunks:
            self.assertEqual(c.page_start, c.page_end)
            self.assertEqual(c.slide_number, c.page_start)
        caching = next(c for c in chunks if c.slide_number == 3 and c.kind == "text")
        self.assertTrue(caching.embedding_text.startswith("CS101 | Slide 3: Caching"))
        self.assertEqual(caching.citation_label, "slide 3 > Caching")

    def test_title_only_slide_is_not_indexed(self) -> None:
        chunker_ = chunker()
        result = chunker_.run(self.slide_doc(), CTX)

        self.assertNotIn(2, {c.slide_number for c in result.chunks})
        self.assertEqual(result.report.skipped_slides, [2])

    def test_notes_are_a_separate_chunk(self) -> None:
        chunks = chunker().chunk(self.slide_doc(), CTX)
        notes = [c for c in chunks if c.kind == "notes"]
        body = next(c for c in chunks if c.slide_number == 3 and c.kind == "text")

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].slide_number, 3)
        self.assertIn("[Speaker Notes]", notes[0].text)
        self.assertNotIn("simulator", body.text)

    def test_hidden_slide_is_excluded(self) -> None:
        result = chunker().run(self.slide_doc(), CTX)

        self.assertNotIn(4, {c.slide_number for c in result.children})
        self.assertEqual(result.report.hidden_slides_excluded, [4])

    def test_slide_with_image_text_is_mixed(self) -> None:
        blocks = [
            H("Diagram", page=1), Pg("Cache hierarchy overview slide text.", page=1),
            Block(BlockType.IMAGE_OCR, "L1 L2 L3 memory", 1, ref_index=0, confidence=0.9),
        ]
        doc = build(blocks, unit="slide", file_type="pptx", metadata={"slides": []})
        chunk = chunker().chunk(doc, CTX)[0]

        self.assertEqual(chunk.source_kind, "mixed")
        self.assertIn("[Image text]", chunk.text)
        self.assertAlmostEqual(chunk.confidence, 0.9)


class OcrTests(unittest.TestCase):
    def test_pdf_image_ocr_is_not_merged_with_native_text(self) -> None:
        blocks = [
            H("Figure"), Pg("Native paragraph about the figure."),
            Block(BlockType.IMAGE_OCR, "words recognised in image", 1, ref_index=0, confidence=0.8),
        ]
        chunks = chunker().chunk(build(blocks), CTX)

        self.assertEqual(sorted(c.kind for c in chunks), ["image_ocr", "text"])
        image = next(c for c in chunks if c.kind == "image_ocr")
        self.assertEqual(image.source_kind, "image_ocr")
        self.assertTrue(image.text.startswith("[Image text]"))
        self.assertAlmostEqual(image.confidence, 0.8)

    def test_low_confidence_image_ocr_is_dropped(self) -> None:
        blocks = [H("F"), Pg("text text text."),
                  Block(BlockType.IMAGE_OCR, "noise", 1, ref_index=0, confidence=0.2)]
        result = chunker().run(build(blocks), CTX)

        self.assertEqual([c.kind for c in result.chunks], ["text"])
        self.assertEqual(result.report.dropped_blocks, 1)

    def test_ocr_page_is_flagged_and_very_low_pages_are_dropped(self) -> None:
        pages = [
            PageContent(page_number=1, ocr_applied=True, confidence=0.5),
            PageContent(page_number=2, ocr_applied=True, confidence=0.2),
        ]
        blocks = [H("Scan", page=1), Pg(sentences(2), page=1), Pg(sentences(2, prefix="q"), page=2)]
        result = chunker().run(build(blocks, pages=pages), CTX)

        self.assertEqual(result.report.skipped_pages, [2])
        chunk = result.chunks[0]
        self.assertEqual(chunk.source_kind, "ocr_page")
        self.assertTrue(chunk.low_confidence)
        self.assertAlmostEqual(chunk.confidence, 0.5)

    def test_office_page_confidence_does_not_flag_text_chunks(self) -> None:
        pages = [PageContent(page_number=1, confidence=0.0)]  # e.g. one failed image
        doc = build([H("Doc"), Pg(sentences(2))], unit="document", file_type="docx", pages=pages)
        chunk = chunker().chunk(doc, CTX)[0]

        self.assertFalse(chunk.low_confidence)
        self.assertEqual(chunk.citation_label, "Doc")


class IdentityTests(unittest.TestCase):
    def test_deterministic_ids_and_content_sensitivity(self) -> None:
        def make(text: str) -> Document:
            return build([H("A"), Pg(sentences(5, per=9, prefix="a")), H("B"), Pg(text)])

        one = chunker().chunk(make(sentences(5, per=9, prefix="b")), CTX)
        two = chunker().chunk(make(sentences(5, per=9, prefix="b")), CTX)
        edited = chunker().chunk(make(sentences(5, per=9, prefix="B")), CTX)

        self.assertEqual([c.chunk_id for c in one], [c.chunk_id for c in two])
        self.assertEqual([c.embedding_text for c in one], [c.embedding_text for c in two])
        changed = [i for i, (a, b) in enumerate(zip(one, edited)) if a.chunk_id != b.chunk_id]
        self.assertEqual([one[i].heading_path for i in changed], [("B",)])
        self.assertEqual(one[0].content_hash, edited[0].content_hash)  # section A untouched

    def test_chunk_id_format_and_vector_id(self) -> None:
        chunk = chunker().chunk(build([H("A"), Pg(sentences(2))]), CTX)[0]

        self.assertRegex(chunk.chunk_id, r"^c-[0-9a-f]{12}$")  # content-addressed, no file hash, no position
        self.assertEqual(chunk.vector_id, f"doc-1:{chunk.chunk_id}")

    def test_chroma_metadata_is_flat_scalars(self) -> None:
        chunk = chunker().chunk(build([H("A"), H("B", 2), Pg(sentences(2))]), CTX)[0]
        meta = chunk.chroma_metadata()

        for key, value in meta.items():
            self.assertIsInstance(value, (str, int, float, bool), key)
        self.assertEqual(meta["heading_path"], "A > B")
        self.assertEqual(meta["heading_top"], "A")
        self.assertEqual(meta["slide_number"], -1)
        self.assertEqual(meta["user_id"], "u1")
        self.assertEqual(meta["course_id"], "c1")
        record = chunk.to_chroma_record()
        self.assertEqual(record["document"], chunk.text)

    def test_collection_name_and_config_validation(self) -> None:
        self.assertEqual(collection_name(), "chunks__bge-small-en-v1.5__c1")
        with self.assertRaises(ValueError):
            ChunkConfig(target_tokens=100, max_tokens=50)


if __name__ == "__main__":
    unittest.main()

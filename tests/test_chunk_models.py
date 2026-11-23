"""Chunk / ParentChunk / ChildChunk model tests (schema step of the design)."""

from __future__ import annotations

import unittest

from ai.chunking.citation import block_ranges, citation_label
from ai.chunking.engine import ChunkingEngine
from ai.chunking.models import ChildChunk, Chunk, ParentChunk
from tests.chunk_fixtures import CTX, OCR, SMALL, H, Pg, WordCounter, build, sentences


def engine() -> ChunkingEngine:
    return ChunkingEngine(SMALL, WordCounter())


class HierarchyTests(unittest.TestCase):
    def test_models_share_a_base_class(self) -> None:
        self.assertTrue(issubclass(ChildChunk, Chunk))
        self.assertTrue(issubclass(ParentChunk, Chunk))

    def test_parent_is_not_embeddable(self) -> None:
        result = engine().run(build([H("A"), Pg(sentences(2))]), CTX)

        self.assertFalse(hasattr(result.parents[0], "embedding_text"))
        self.assertTrue(hasattr(result.children[0], "embedding_text"))


class HelperTests(unittest.TestCase):
    def test_block_ranges_collapse_runs(self) -> None:
        self.assertEqual(block_ranges((3, 4, 5, 7, 9, 10)), ((3, 5), (7, 7), (9, 10)))
        self.assertEqual(block_ranges(()), ())
        self.assertEqual(block_ranges((2,)), ((2, 2),))

    def test_citation_labels(self) -> None:
        self.assertEqual(citation_label("page", 4, 4, ("A", "B")), "p. 4 > A > B")
        self.assertEqual(citation_label("page", 4, 5, ("A",)), "p. 4-5 > A")
        self.assertEqual(citation_label("slide", 7, 7, ("Cache",)), "slide 7 > Cache")
        self.assertEqual(citation_label("document", 1, 1, ("A", "B")), "A > B")
        self.assertEqual(citation_label("document", 1, 1, ()), "document")


class RequiredMetadataTests(unittest.TestCase):
    """Every chunk carries the fields the RAG layer needs (final decisions)."""

    def setUp(self) -> None:
        blocks = [H("Caching"), Pg("Intro sentence. " * 3), Pg("Second paragraph here now.")]
        self.doc = build(blocks, title="OS Notes", author="Dr. Ahmed", language="en")
        self.child = engine().run(self.doc, CTX).children[0]

    def test_identity_and_document_metadata(self) -> None:
        self.assertRegex(self.child.chunk_id, r"^c-[0-9a-f]{12}$")
        self.assertEqual(self.child.doc_id, "d0c0000000000001")
        self.assertEqual(self.child.title, "OS Notes")
        self.assertEqual(self.child.author, "Dr. Ahmed")
        self.assertEqual(self.child.language, "en")
        self.assertEqual(self.child.file_type, "pdf")

    def test_location_and_structure_fields(self) -> None:
        self.assertEqual(self.child.heading_path, ("Caching",))
        self.assertEqual(self.child.page_number, 1)
        self.assertIsNone(self.child.slide_number)
        self.assertEqual(self.child.citation_label, "p. 1 > Caching")
        self.assertEqual(self.child.block_ranges, ((1, 2),))
        self.assertEqual(self.child.block_types, ("paragraph",))

    def test_ocr_confidence_is_none_for_native_text(self) -> None:
        self.assertIsNone(self.child.ocr_confidence)

    def test_ocr_confidence_is_preserved_and_minimal(self) -> None:
        blocks = [H("F"), OCR("first ocr words here", 0.9, ref=0), OCR("second ocr words", 0.7, ref=1)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata={"slides": []})
        children = engine().run(doc, CTX).children

        self.assertEqual(len(children), 1)
        self.assertAlmostEqual(children[0].ocr_confidence, 0.7)
        self.assertIn("image_ocr", children[0].block_types)

    def test_chroma_metadata_has_required_keys_and_only_scalars(self) -> None:
        meta = self.child.chroma_metadata()
        required = {
            "chunk_id", "doc_id", "heading_path", "citation_label", "page_number",
            "slide_number", "block_ranges", "block_types", "ocr_confidence", "title",
            "author", "language", "file_name", "file_type", "parent_chunk_id", "content_hash",
            "embedding_hash", "user_id", "course_id", "document_uid", "low_confidence",
        }
        self.assertTrue(required <= set(meta), required - set(meta))
        for key, value in meta.items():
            self.assertIsInstance(value, (str, int, float, bool), key)
        self.assertEqual(meta["block_ranges"], "1-2")
        self.assertEqual(meta["ocr_confidence"], -1.0)
        self.assertEqual(meta["slide_number"], -1)
        self.assertEqual(meta["parent_chunk_id"], self.child.parent_id)


if __name__ == "__main__":
    unittest.main()

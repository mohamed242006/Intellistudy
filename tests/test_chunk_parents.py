"""Hierarchical (parent / child) chunking tests."""

from __future__ import annotations

import dataclasses
import unittest

from ai.chunking.engine import ChunkingEngine
from tests.chunk_fixtures import CTX, SMALL, H, Pg, WordCounter, build, sentences, slide_meta


def engine(config=SMALL) -> ChunkingEngine:
    return ChunkingEngine(config, WordCounter())


class ParentChildTests(unittest.TestCase):
    def doc(self):
        return build([
            H("Caching"), Pg(sentences(5, per=9, prefix="a")),
            H("LRU", 2), Pg(sentences(5, per=9, prefix="b")),
            H("Networking"), Pg(sentences(5, per=9, prefix="c")),
        ])

    def test_every_child_has_an_existing_parent_and_back_links_match(self) -> None:
        result = engine().run(self.doc(), CTX)
        parents = {p.chunk_id: p for p in result.parents}

        for child in result.children:
            self.assertIn(child.parent_id, parents)
            self.assertIn(child.chunk_id, parents[child.parent_id].child_ids)
        linked = [cid for p in result.parents for cid in p.child_ids]
        self.assertEqual(sorted(linked), sorted(c.chunk_id for c in result.children))

    def test_parents_follow_sections_and_heading_paths(self) -> None:
        result = engine().run(self.doc(), CTX)

        self.assertEqual(
            [p.heading_path for p in result.parents],
            [("Caching",), ("Caching", "LRU"), ("Networking",)],
        )
        for parent in result.parents:
            children = result.children_of(parent)
            self.assertTrue(all(c.heading_path == parent.heading_path for c in children))

    def test_parent_text_is_its_children_in_order_without_overlap(self) -> None:
        result = engine().run(self.doc(), CTX)

        for parent in result.parents:
            joined = "\n\n".join(c.text for c in result.children_of(parent))
            self.assertEqual(parent.text, joined)
        # overlap sentences only exist in embedding_text, so they are not duplicated here
        for child in result.children:
            if child.overlap_prefix:
                parent = result.parent_of(child)
                self.assertEqual(parent.text.count(child.overlap_prefix), 1)

    def test_parent_provenance_and_citation(self) -> None:
        result = engine().run(self.doc(), CTX)
        parent = result.parents[1]

        self.assertEqual(parent.citation_label, "p. 1 > Caching > LRU")
        self.assertEqual(parent.doc_id, "d0c0000000000001")
        self.assertEqual(parent.user_id, "u1")
        self.assertEqual(parent.course_id, "c1")
        first, last = result.children_of(parent)[0], result.children_of(parent)[-1]
        self.assertEqual(parent.block_start, first.block_start)
        self.assertEqual(parent.block_end, last.block_end)

    def test_large_section_is_split_into_consecutive_parents(self) -> None:
        doc = build([H("Long")] + [Pg(sentences(1, per=20, prefix=f"p{i}")) for i in range(14)])
        result = engine().run(doc, CTX)

        self.assertGreater(len(result.parents), 1)
        for parent in result.parents:
            self.assertLessEqual(parent.token_count, SMALL.parent_max_tokens + SMALL.max_tokens)
            self.assertEqual(parent.heading_path, ("Long",))
        self.assertEqual(len({p.chunk_id for p in result.parents}), len(result.parents))

    def test_each_slide_has_its_own_parent(self) -> None:
        blocks = [
            H("One", page=1), Pg(sentences(3), page=1),
            H("Two", page=2), Pg(sentences(3, prefix="t"), page=2),
        ]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=2))
        result = engine().run(doc, CTX)

        self.assertEqual([(p.page_start, p.page_end) for p in result.parents], [(1, 1), (2, 2)])
        self.assertEqual([p.slide_number for p in result.parents], [1, 2])

    def test_notes_child_belongs_to_the_slide_parent(self) -> None:
        from ai.ingestion.models import Block, BlockType

        blocks = [H("One"), Pg(sentences(3)), Block(BlockType.NOTES, "speaker words here now", 1)]
        doc = build(blocks, unit="slide", file_type="pptx", metadata=slide_meta(count=1))
        result = engine().run(doc, CTX)

        self.assertEqual(len(result.parents), 1)
        self.assertEqual({c.kind for c in result.children}, {"text", "notes"})

    def test_ids_are_deterministic_and_prefixed(self) -> None:
        one, two = engine().run(self.doc(), CTX), engine().run(self.doc(), CTX)

        self.assertEqual([p.chunk_id for p in one.parents], [p.chunk_id for p in two.parents])
        self.assertRegex(one.parents[0].chunk_id, r"^d0c0000000000001-P\d{4}-[0-9a-f]{8}$")

    def test_parent_ids_do_not_change_child_ids(self) -> None:
        small = engine().run(self.doc(), CTX)
        other = engine(dataclasses.replace(SMALL, parent_max_tokens=SMALL.max_tokens)).run(self.doc(), CTX)

        self.assertEqual([c.chunk_id for c in small.children], [c.chunk_id for c in other.children])


if __name__ == "__main__":
    unittest.main()

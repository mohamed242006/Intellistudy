"""Re-ingestion without duplicate vectors, behind the Embedder / VectorStore interfaces."""

from __future__ import annotations

import unittest

from ai.chunking.config import collection_name
from ai.chunking.engine import ChunkingEngine
from ai.chunking.errors import IndexingError
from ai.chunking.indexing import IndexingService, ReingestPlanner
from ai.chunking.memory_store import InMemoryParentStore, InMemoryVectorStore
from tests.chunk_fixtures import CTX, SMALL, FakeEmbedder, H, Pg, WordCounter, build, sentences

COLLECTION = collection_name("fake-embed")


def section(title: str, prefix: str, per: int = 8, n: int = 3):
    return [H(title), Pg(sentences(n, per=per, prefix=prefix))]


def make_set(*sections, ctx=CTX):
    blocks = [b for s in sections for b in s]
    return ChunkingEngine(SMALL, WordCounter()).run(build(blocks), ctx)


def make_chunks(*sections, ctx=CTX):
    return make_set(*sections, ctx=ctx).children


class IndexingTestCase(unittest.TestCase):
    """Backend-agnostic: subclasses override ``new_store`` / ``new_parent_store``."""

    def new_store(self):
        return InMemoryVectorStore()

    def new_parent_store(self):
        return InMemoryParentStore()

    def setUp(self) -> None:
        self.embedder = FakeEmbedder()
        self.store = self.new_store()
        self.parent_store = self.new_parent_store()
        self.service = IndexingService(self.embedder, self.store, parent_store=self.parent_store)

    def ids(self, uid: str = "doc-1") -> dict[str, str]:
        return self.store.list_ids(COLLECTION, document_uid=uid)


class FirstIndexTests(IndexingTestCase):
    def test_all_chunks_are_embedded_and_stored(self) -> None:
        chunks = make_chunks(section("A", "a"), section("B", "b"), section("C", "c"))
        report = self.service.index(chunks, document_uid="doc-1")

        self.assertEqual((report.embedded, report.reused, report.unchanged, report.deleted), (3, 0, 0, 0))
        self.assertEqual(set(self.ids()), {c.vector_id for c in chunks})
        self.assertEqual(self.embedder.texts_embedded, [c.embedding_text for c in chunks])

    def test_documents_are_embedded_in_batches(self) -> None:
        chunks = make_chunks(*[section(f"S{i}", f"s{i}") for i in range(5)])
        service = IndexingService(self.embedder, self.store, batch_size=2)
        service.index(chunks, document_uid="doc-1")

        self.assertEqual(self.embedder.document_calls, 3)


class ReingestionTests(IndexingTestCase):
    def test_reingesting_identical_content_is_a_noop(self) -> None:
        chunks = make_chunks(section("A", "a"), section("B", "b"))
        self.service.index(chunks, document_uid="doc-1")
        before = len(self.embedder.texts_embedded)
        report = self.service.index(chunks, document_uid="doc-1")

        self.assertEqual((report.embedded, report.reused, report.deleted, report.unchanged), (0, 0, 0, 2))
        self.assertEqual(len(self.embedder.texts_embedded), before)
        self.assertEqual(self.store.count(COLLECTION), 2)

    def test_editing_one_section_embeds_only_that_chunk_and_leaves_no_duplicates(self) -> None:
        old = make_chunks(section("A", "a"), section("B", "b"), section("C", "c"))
        self.service.index(old, document_uid="doc-1")
        before = len(self.embedder.texts_embedded)
        new = make_chunks(section("A", "a"), section("B", "EDITED"), section("C", "c"))
        report = self.service.index(new, document_uid="doc-1")

        self.assertEqual((report.embedded, report.unchanged, report.deleted), (1, 2, 1))
        self.assertEqual(len(self.embedder.texts_embedded) - before, 1)
        self.assertEqual(set(self.ids()), {c.vector_id for c in new})
        self.assertEqual(self.store.count(COLLECTION), 3)

    def test_inserting_a_section_keeps_the_ids_of_the_others(self) -> None:
        old = make_chunks(section("A", "a"), section("B", "b"), section("C", "c"))
        self.service.index(old, document_uid="doc-1")
        before = len(self.embedder.texts_embedded)
        new = make_chunks(section("New", "n"), section("A", "a"), section("B", "b"), section("C", "c"))
        report = self.service.index(new, document_uid="doc-1")

        self.assertEqual(report.embedded, 1)          # only the new section
        self.assertEqual(report.reused, 0)            # ids do not depend on position: nothing is re-keyed
        self.assertEqual(report.unchanged + report.refreshed, 3)  # the others keep id and vector (metadata refreshed)
        self.assertEqual(report.deleted, 0)           # and nothing is retired
        self.assertEqual(len(self.embedder.texts_embedded) - before, 1)
        self.assertEqual(set(self.ids()), {c.vector_id for c in new})
        self.assertEqual(self.store.count(COLLECTION), 4)

    def test_removed_section_is_deleted(self) -> None:
        old = make_chunks(section("A", "a"), section("B", "b"))
        self.service.index(old, document_uid="doc-1")
        self.service.index(make_chunks(section("A", "a")), document_uid="doc-1")

        self.assertEqual(self.store.count(COLLECTION), 1)

    def test_empty_chunk_list_removes_the_document(self) -> None:
        self.service.index(make_chunks(section("A", "a")), document_uid="doc-1")
        report = self.service.index([], document_uid="doc-1")

        self.assertEqual(report.deleted, 1)
        self.assertEqual(self.store.count(COLLECTION), 0)

    def test_other_documents_are_untouched(self) -> None:
        other_ctx = CTX.__class__(user_id="u1", course_id="c1", document_uid="doc-2",
                                  embedding_model="fake-embed")
        self.service.index(make_chunks(section("A", "a")), document_uid="doc-1")
        self.service.index(make_chunks(section("Z", "z"), ctx=other_ctx), document_uid="doc-2")
        self.service.remove_document("doc-1")

        self.assertEqual(self.ids("doc-1"), {})
        self.assertEqual(len(self.ids("doc-2")), 1)

    def test_failed_embedding_leaves_the_store_untouched(self) -> None:
        old = make_chunks(section("A", "a"), section("B", "b"))
        self.service.index(old, document_uid="doc-1")
        snapshot = dict(self.ids())

        class Broken(FakeEmbedder):
            def embed_documents(self, texts):
                raise RuntimeError("model unavailable")

        service = IndexingService(Broken(), self.store)
        with self.assertRaises(RuntimeError):
            service.index(make_chunks(section("A", "a"), section("B", "CHANGED")), document_uid="doc-1")
        self.assertEqual(self.ids(), snapshot)


class PlannerTests(unittest.TestCase):
    def test_plan_classification(self) -> None:
        old = make_chunks(section("A", "a"), section("B", "b"))
        existing = {c.vector_id: c.embedding_hash for c in old}
        new = make_chunks(section("A", "a"), section("B", "b2"), section("C", "c"))
        plan = ReingestPlanner().plan(existing, new)

        self.assertEqual(plan.unchanged, [new[0].vector_id])
        self.assertEqual({c.vector_id for c in plan.embed}, {new[1].vector_id, new[2].vector_id})
        self.assertEqual(plan.delete, [old[1].vector_id])
        self.assertEqual(plan.reuse, {})

    def test_same_id_with_different_embedding_text_is_re_embedded_not_skipped(self) -> None:
        chunks = make_chunks(section("A", "a"))
        existing = {chunks[0].vector_id: "stale-hash"}
        plan = ReingestPlanner().plan(existing, chunks)

        self.assertEqual([c.vector_id for c in plan.embed], [chunks[0].vector_id])
        self.assertEqual(plan.delete, [])  # same id: overwritten by the upsert, not deleted


class ParentHandlingTests(IndexingTestCase):
    """Parents are stored relationally and are NEVER embedded."""

    def big(self, prefix: str = "a"):
        return [H("Topic"), Pg(sentences(6, per=9, prefix=prefix))]  # splits into 2 children

    def test_only_children_are_embedded_and_parents_go_to_the_parent_store(self) -> None:
        chunk_set = make_set(self.big("a"), section("Other", "b"))
        self.service.index(chunk_set.children, document_uid="doc-1", parents=chunk_set.parents)

        self.assertGreater(len(chunk_set.parents), 0)
        self.assertEqual(set(self.embedder.texts_embedded), {c.embedding_text for c in chunk_set.children})
        for parent in chunk_set.parents:
            self.assertNotIn(parent.text, self.embedder.texts_embedded)
            self.assertFalse(any(parent.chunk_id in vid for vid in self.ids()))
        self.assertEqual(set(self.ids()), {c.vector_id for c in chunk_set.children})
        self.assertEqual(self.parent_store.list_ids(document_uid="doc-1"),
                         {p.store_key for p in chunk_set.parents})

    def test_a_parent_chunk_is_rejected_as_an_embedding_input(self) -> None:
        chunk_set = make_set(self.big())
        with self.assertRaises(IndexingError):
            self.service.index([*chunk_set.children, chunk_set.parents[0]], document_uid="doc-1")  # type: ignore[list-item]
        self.assertEqual(self.embedder.texts_embedded, [])
        self.assertEqual(self.store.count(COLLECTION), 0)

    def test_parents_are_replaced_on_reingestion_and_stale_ones_removed(self) -> None:
        first = make_set(self.big("a"), section("Gone", "g"))
        self.service.index(first.children, document_uid="doc-1", parents=first.parents)
        second = make_set(self.big("a"))
        report = self.service.index(second.children, document_uid="doc-1", parents=second.parents)

        self.assertGreaterEqual(report.parents_deleted, 1)
        self.assertEqual(self.parent_store.list_ids(document_uid="doc-1"),
                         {p.store_key for p in second.parents})

    def test_parents_none_leaves_parents_untouched_and_empty_list_removes_them(self) -> None:
        chunk_set = make_set(self.big())
        self.service.index(chunk_set.children, document_uid="doc-1", parents=chunk_set.parents)
        self.service.index(chunk_set.children, document_uid="doc-1")  # parents=None
        self.assertEqual(len(self.parent_store.list_ids(document_uid="doc-1")), len(chunk_set.parents))

        self.service.index(chunk_set.children, document_uid="doc-1", parents=[])
        self.assertEqual(self.parent_store.list_ids(document_uid="doc-1"), set())

    def test_parents_without_a_parent_store_are_an_error(self) -> None:
        chunk_set = make_set(self.big())
        service = IndexingService(self.embedder, self.store)  # no parent store
        with self.assertRaises(IndexingError):
            service.index(chunk_set.children, document_uid="doc-1", parents=chunk_set.parents)

    def test_parents_of_another_document_are_rejected(self) -> None:
        other = CTX.__class__(user_id="u1", course_id="c1", document_uid="doc-9", embedding_model="fake-embed")
        foreign = make_set(self.big(), ctx=other)
        mine = make_set(self.big())
        with self.assertRaises(IndexingError):
            self.service.index(mine.children, document_uid="doc-1", parents=foreign.parents)

    def test_remove_document_deletes_vectors_and_parents(self) -> None:
        chunk_set = make_set(self.big())
        self.service.index(chunk_set.children, document_uid="doc-1", parents=chunk_set.parents)
        removed = self.service.remove_document("doc-1")

        self.assertEqual(removed, len(chunk_set.children))
        self.assertEqual(self.ids(), {})
        self.assertEqual(self.parent_store.list_ids(document_uid="doc-1"), set())


class GuardTests(IndexingTestCase):
    def test_embedder_model_must_match_chunk_metadata(self) -> None:
        wrong = CTX.__class__(user_id="u1", course_id="c1", document_uid="doc-1", embedding_model="other")
        with self.assertRaises(IndexingError):
            self.service.index(make_chunks(section("A", "a"), ctx=wrong), document_uid="doc-1")
        self.assertEqual(self.store.count(COLLECTION), 0)

    def test_dimension_is_validated(self) -> None:
        class Short(FakeEmbedder):
            def embed_documents(self, texts):
                return [[0.1, 0.2] for _ in texts]

        with self.assertRaises(IndexingError):
            IndexingService(Short(), self.store).index(
                make_chunks(section("A", "a")), document_uid="doc-1"
            )

    def test_chunks_must_belong_to_the_document(self) -> None:
        with self.assertRaises(IndexingError):
            self.service.index(make_chunks(section("A", "a")), document_uid="someone-else")


class QueryTests(IndexingTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.chunks = make_chunks(
            [H("Caching"), Pg("lru eviction removes the least recently used entry first today now.")],
            [H("Networking"), Pg("tcp handshake uses syn and ack packets between client and server.")],
        )
        self.service.index(self.chunks, document_uid="doc-1")

    def query(self, text: str, **scope):
        vector = self.embedder.embed_query(text)
        params = {"user_id": "u1", "course_id": "c1", "k": 2}
        params.update(scope)
        return self.store.query(COLLECTION, vector, **params)

    def test_best_match_carries_citation_and_parent_link(self) -> None:
        top = self.query("least recently used eviction")[0]

        self.assertEqual(top.metadata["heading_path"], "Caching")
        self.assertEqual(top.metadata["citation_label"], "p. 1 > Caching")
        self.assertTrue(top.metadata["parent_chunk_id"])
        self.assertTrue(top.document.startswith("lru eviction"))

    def test_scope_is_enforced_server_side(self) -> None:
        self.assertEqual(self.query("tcp", user_id="intruder"), [])
        self.assertEqual(self.query("tcp", course_id="other-course"), [])
        with self.assertRaises(ValueError):
            self.query("tcp", user_id="")

    def test_filters_narrow_the_search(self) -> None:
        hits = self.query("tcp", filters={"heading_top": "Caching"})

        self.assertEqual({h.metadata["heading_top"] for h in hits}, {"Caching"})


if __name__ == "__main__":
    unittest.main()

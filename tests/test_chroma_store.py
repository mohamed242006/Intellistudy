"""ChromaVectorStore: the full indexing suite re-run on Chroma, plus Chroma-specific checks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import chromadb
from chromadb.config import Settings

from ai.chunking.config import collection_name
from ai.chunking.indexing import IndexingService
from ai.chunking.interfaces import VectorRecord, VectorStore
from ai.chunking.memory_store import InMemoryParentStore
from ai.vectorstore import ChromaVectorStore
from tests import test_chunk_indexing as base
from tests.chunk_fixtures import FakeEmbedder

COLLECTION = collection_name("fake-embed")


def fresh_client():
    """In-process Chroma is shared between instances: reset it so each test starts empty."""
    client = chromadb.EphemeralClient(settings=Settings(allow_reset=True, anonymized_telemetry=False))
    client.reset()
    return client


class ChromaBackend:
    """Mixin: run an inherited test case against ChromaVectorStore."""

    def new_store(self):
        client = fresh_client()
        self.addCleanup(client.reset)
        return ChromaVectorStore(client)


# --- the entire backend-agnostic indexing suite, unchanged, on Chroma ---------------------
class ChromaFirstIndex(ChromaBackend, base.FirstIndexTests):
    pass


class ChromaReingestion(ChromaBackend, base.ReingestionTests):
    pass


class ChromaParentHandling(ChromaBackend, base.ParentHandlingTests):
    pass


class ChromaGuards(ChromaBackend, base.GuardTests):
    pass


class ChromaQueries(ChromaBackend, base.QueryTests):
    pass


# --- Chroma specific -----------------------------------------------------------------------
class ChromaSpecificTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = fresh_client()
        self.addCleanup(self.client.reset)
        self.store = ChromaVectorStore(self.client)
        self.embedder = FakeEmbedder()
        self.parents = InMemoryParentStore()
        self.service = IndexingService(self.embedder, self.store, parent_store=self.parents)

    def index(self, *sections, uid: str = "doc-1"):
        chunk_set = base.make_set(*sections)
        self.service.index(chunk_set.children, document_uid=uid, parents=chunk_set.parents)
        return chunk_set

    def test_satisfies_the_vector_store_protocol(self) -> None:
        self.assertIsInstance(self.store, VectorStore)

    def test_stores_everything_the_rag_layer_needs(self) -> None:
        chunk_set = self.index(base.section("Caching", "a"))
        child = chunk_set.children[0]
        col = self.client.get_collection(COLLECTION, embedding_function=None)
        got = col.get(include=["metadatas", "embeddings", "documents"])

        self.assertEqual(got["ids"], [child.vector_id])
        meta = got["metadatas"][0]
        for key in ("chunk_id", "parent_chunk_id", "doc_id", "heading_path", "citation_label",
                    "page_number", "slide_number", "block_types", "ocr_confidence",
                    "user_id", "course_id"):
            self.assertIn(key, meta)
        self.assertEqual(meta["chunk_id"], child.chunk_id)
        self.assertEqual(meta["parent_chunk_id"], child.parent_id)
        self.assertEqual(meta["doc_id"], "d0c0000000000001")
        self.assertEqual(meta["heading_path"], "Caching")
        self.assertEqual(meta["citation_label"], "p. 1 > Caching")
        self.assertEqual((meta["page_number"], meta["slide_number"]), (1, -1))
        self.assertEqual(meta["block_types"], "paragraph")
        self.assertEqual(meta["ocr_confidence"], -1.0)
        self.assertEqual((meta["user_id"], meta["course_id"]), ("u1", "c1"))
        self.assertEqual(got["documents"][0], child.text)
        self.assertEqual(len(got["embeddings"][0]), self.embedder.dimension)

    def test_chroma_stores_our_vectors_not_its_own(self) -> None:
        child = self.index(base.section("Caching", "a")).children[0]
        stored = self.store.get_embeddings(COLLECTION, [child.vector_id])[child.vector_id]
        ours = self.embedder.embed_documents([child.embedding_text])[0]

        self.assertEqual(len(stored), len(ours))
        for a, b in zip(stored, ours):
            self.assertAlmostEqual(a, b, places=5)

    def test_parents_never_enter_the_collection(self) -> None:
        chunk_set = self.index([base.H("Topic"), base.Pg(base.sentences(6, per=9))])
        col = self.client.get_collection(COLLECTION, embedding_function=None)
        stored_ids = set(col.get()["ids"])

        self.assertGreater(len(chunk_set.parents), 0)
        self.assertEqual(stored_ids, {c.vector_id for c in chunk_set.children})
        for parent in chunk_set.parents:
            self.assertFalse(any(parent.chunk_id in vid for vid in stored_ids))
        self.assertEqual(self.parents.count(), len(chunk_set.parents))

    def test_cosine_space_scores_identical_vectors_as_one(self) -> None:
        child = self.index(base.section("Caching", "a")).children[0]
        vector = self.store.get_embeddings(COLLECTION, [child.vector_id])[child.vector_id]
        hit = self.store.query(COLLECTION, vector, user_id="u1", course_id="c1", k=1)[0]

        self.assertAlmostEqual(hit.score, 1.0, places=4)

    def test_scope_filters_are_always_applied(self) -> None:
        self.index(base.section("Caching", "a"))
        vector = self.embedder.embed_query("anything")

        self.assertEqual(self.store.query(COLLECTION, vector, user_id="u2", course_id="c1", k=5), [])
        self.assertEqual(self.store.query(COLLECTION, vector, user_id="u1", course_id="c2", k=5), [])
        for kwargs in ({"user_id": "", "course_id": "c1"}, {"user_id": "u1", "course_id": ""}):
            with self.assertRaises(ValueError):
                self.store.query(COLLECTION, vector, k=5, **kwargs)

    def test_reserved_filters_cannot_override_scope(self) -> None:
        self.index(base.section("Caching", "a"))
        with self.assertRaises(ValueError):
            self.store.query(COLLECTION, self.embedder.embed_query("x"), user_id="u1",
                             course_id="c1", k=1, filters={"user_id": "u2"})

    def test_list_filters_use_in_and_empty_list_matches_nothing(self) -> None:
        self.index(base.section("Caching", "a"), uid="doc-1")
        vector = self.embedder.embed_query("lru")
        both = self.store.query(COLLECTION, vector, user_id="u1", course_id="c1", k=5,
                                filters={"document_uid": ["doc-1", "doc-x"]})

        self.assertEqual(len(both), 1)
        self.assertEqual(self.store.query(COLLECTION, vector, user_id="u1", course_id="c1", k=5,
                                          filters={"document_uid": []}), [])

    def test_querying_an_empty_collection_returns_nothing(self) -> None:
        vector = self.embedder.embed_query("x")

        self.assertEqual(self.store.query(COLLECTION, vector, user_id="u1", course_id="c1", k=3), [])
        with self.assertRaises(ValueError):
            self.store.query(COLLECTION, vector, user_id="u1", course_id="c1", k=0)

    def test_large_operations_are_batched(self) -> None:
        self.store._batch = 3  # force several batches
        chunk_set = base.make_set(*[base.section(f"S{i}", f"s{i}") for i in range(8)])
        self.service.index(chunk_set.children, document_uid="doc-1", parents=chunk_set.parents)

        self.assertEqual(self.store.count(COLLECTION), 8)
        self.assertEqual(len(self.store.list_ids(COLLECTION, document_uid="doc-1")), 8)
        deleted = self.store.delete(COLLECTION, [c.vector_id for c in chunk_set.children] + ["ghost"])
        self.assertEqual(deleted, 8)  # only ids that existed are counted

    def test_upsert_overwrites_the_same_id(self) -> None:
        meta = {"document_uid": "d", "embedding_hash": "h1", "user_id": "u", "course_id": "c"}
        self.store.upsert("tmp-collection", [VectorRecord("v1", [1.0, 0.0], "old", meta)])
        self.store.upsert("tmp-collection",
                          [VectorRecord("v1", [0.0, 1.0], "new", {**meta, "embedding_hash": "h2"})])

        self.assertEqual(self.store.count("tmp-collection"), 1)
        self.assertEqual(self.store.list_ids("tmp-collection", document_uid="d"), {"v1": "h2"})

    def test_data_persists_in_a_persistent_client(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "chroma"
            first = ChromaVectorStore(path=path)
            chunk_set = base.make_set(base.section("Caching", "a"))
            IndexingService(self.embedder, first).index(chunk_set.children, document_uid="doc-1")
            del first

            second = ChromaVectorStore(chromadb.PersistentClient(path=str(path)))
            ids = second.list_ids(COLLECTION, document_uid="doc-1")

        self.assertEqual(set(ids), {c.vector_id for c in chunk_set.children})


if __name__ == "__main__":
    unittest.main()

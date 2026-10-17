"""ChromaDB: insert / update / delete / re-index / filtering / metadata correctness / scale.

test_chroma_store.py already re-runs the whole indexing suite on Chroma; this file attacks
the adapter itself with hostile data, real batch boundaries and concurrent writers.
"""

from __future__ import annotations

import re
import threading
import unittest

import chromadb
from chromadb.config import Settings

from ai.chunking import ChunkingEngine, IndexingService, collection_name
from ai.chunking.interfaces import VectorRecord, validate_filters
from ai.chunking.memory_store import InMemoryParentStore
from ai.vectorstore import ChromaVectorStore
from tests.chunk_fixtures import CTX, SMALL, FakeEmbedder, H, Pg, WordCounter, build, sentences
from tests.random_docs import random_document

COLLECTION = collection_name("fake-embed")
SCOPE = {"user_id": "u", "course_id": "c"}


def fresh_client():
    client = chromadb.EphemeralClient(settings=Settings(allow_reset=True, anonymized_telemetry=False))
    client.reset()
    return client


def record(i: int, *, doc: str = "d", dim: int = 4, **meta) -> VectorRecord:
    vector = [0.0] * dim
    vector[i % dim] = 1.0
    vector[(i + 1) % dim] += 0.1 * (i % 7)
    return VectorRecord(f"{doc}:{i}", vector, f"text {i}",
                        {"document_uid": doc, "embedding_hash": f"h{i}", **SCOPE, **meta})


class ChromaTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.client = fresh_client()
        self.addCleanup(self.client.reset)
        self.store = ChromaVectorStore(self.client)


class CrudTests(ChromaTestCase):
    def test_insert_update_delete_cycle(self) -> None:
        self.store.upsert("crud-test", [record(0), record(1)])
        self.assertEqual(self.store.count("crud-test"), 2)

        self.store.upsert("crud-test", [VectorRecord("d:0", [0.0, 0.0, 1.0, 0.0], "rewritten",
                                                     {"document_uid": "d", "embedding_hash": "NEW", **SCOPE})])
        self.assertEqual(self.store.count("crud-test"), 2)  # update, not insert
        self.assertEqual(self.store.list_ids("crud-test", document_uid="d")["d:0"], "NEW")
        hit = self.store.query("crud-test", [0.0, 0.0, 1.0, 0.0], k=1, **SCOPE)[0]
        self.assertEqual((hit.id, hit.document), ("d:0", "rewritten"))

        self.assertEqual(self.store.delete("crud-test", ["d:0", "d:1", "d:never"]), 2)
        self.assertEqual(self.store.count("crud-test"), 0)
        self.assertEqual(self.store.delete("crud-test", []), 0)

    def test_empty_operations_are_noops(self) -> None:
        self.store.upsert("noop-test", [])
        self.assertEqual(self.store.count("noop-test"), 0)
        self.assertEqual(self.store.get_embeddings("noop-test", []), {})
        self.assertEqual(self.store.list_ids("noop-test", document_uid="nothing"), {})

    def test_get_embeddings_returns_only_existing_ids(self) -> None:
        self.store.upsert("emb-test", [record(0), record(1)])
        got = self.store.get_embeddings("emb-test", ["d:0", "ghost"])

        self.assertEqual(set(got), {"d:0"})
        self.assertEqual(len(got["d:0"]), 4)
        self.assertTrue(all(isinstance(x, float) for x in got["d:0"]))

    def test_documents_are_isolated_by_document_uid(self) -> None:
        self.store.upsert("iso-test", [record(0, doc="a"), record(1, doc="a"), record(0, doc="b")])

        self.assertEqual(set(self.store.list_ids("iso-test", document_uid="a")), {"a:0", "a:1"})
        self.assertEqual(set(self.store.list_ids("iso-test", document_uid="b")), {"b:0"})

    def test_collections_are_separate_namespaces_and_can_be_dropped(self) -> None:
        self.store.upsert("coll-one", [record(0)])
        self.store.upsert("coll-two", [record(0), record(1)])
        self.store.drop_collection("coll-one")

        self.assertEqual(self.store.count("coll-two"), 2)
        self.assertEqual(self.store.count("coll-one"), 0)  # recreated empty on demand


class FilterTests(ChromaTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store.upsert("flt-test", [
            record(0, kind="text", low_confidence=False, page_number=1, heading_top="A", score_band=0.5),
            record(1, kind="table", low_confidence=False, page_number=2, heading_top="A", score_band=0.9),
            record(2, kind="text", low_confidence=True, page_number=3, heading_top="B", score_band=0.1),
            record(3, kind="notes", low_confidence=False, page_number=3, heading_top="B", score_band=0.5),
        ])

    def ids(self, **filters) -> set[str]:
        hits = self.store.query("flt-test", [1.0, 0.2, 0.1, 0.0], k=10, filters=filters, **SCOPE)
        return {h.id for h in hits}

    def test_filters_on_every_scalar_type(self) -> None:
        self.assertEqual(self.ids(kind="text"), {"d:0", "d:2"})
        self.assertEqual(self.ids(low_confidence=True), {"d:2"})
        self.assertEqual(self.ids(low_confidence=False), {"d:0", "d:1", "d:3"})
        self.assertEqual(self.ids(page_number=3), {"d:2", "d:3"})
        self.assertEqual(self.ids(score_band=0.5), {"d:0", "d:3"})

    def test_filters_combine_with_and_and_lists_mean_one_of(self) -> None:
        self.assertEqual(self.ids(kind="text", heading_top="B"), {"d:2"})
        self.assertEqual(self.ids(kind=["table", "notes"]), {"d:1", "d:3"})
        self.assertEqual(self.ids(page_number=[1, 2], low_confidence=False), {"d:0", "d:1"})
        self.assertEqual(self.ids(kind="text", heading_top="Z"), set())
        self.assertEqual(self.ids(kind=[]), set())

    def test_unknown_metadata_key_matches_nothing_instead_of_everything(self) -> None:
        self.assertEqual(self.ids(no_such_key="x"), set())

    def test_filter_values_cannot_inject_backend_operators(self) -> None:
        """REG-06: operator dicts / odd keys are rejected before they reach the database."""
        for bad in ({"kind": {"$ne": "text"}}, {"kind": {"$eq": "text"}}, {"kind": None},
                    {"kind": [["nested"]]}, {"kind": [{"$gt": 1}]}, {"$or": "x"}, {"": "x"},
                    {"kind": object()}, {"user_id": "someone-else"}, {"course_id": "other"}):
            with self.subTest(filters=repr(bad)), self.assertRaises(ValueError):
                self.store.query("flt-test", [1.0, 0.0, 0.0, 0.0], k=3, filters=bad, **SCOPE)

    def test_validate_filters_accepts_valid_input_and_copies_it(self) -> None:
        source = {"kind": "text", "page_number": [1, 2], "low_confidence": False}
        clean = validate_filters(source)

        self.assertEqual(clean, source)
        self.assertIsNot(clean, source)
        self.assertEqual(validate_filters(None), {})

    def test_hostile_strings_are_just_data(self) -> None:
        self.store.upsert("flt-test", [record(9, kind="x') OR 1=1 --")])

        self.assertEqual(self.ids(kind="x') OR 1=1 --"), {"d:9"})
        self.assertEqual(self.ids(kind="' OR '1'='1"), set())


class MetadataCorrectnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = fresh_client()
        self.addCleanup(self.client.reset)
        self.store = ChromaVectorStore(self.client)
        self.embedder = FakeEmbedder(dimension=64)
        self.parents = InMemoryParentStore()
        self.service = IndexingService(self.embedder, self.store, parent_store=self.parents)

    def test_every_stored_record_equals_what_the_chunker_produced(self) -> None:
        for unit, seed in (("page", 3), ("slide", 4), ("document", 5)):
            with self.subTest(unit=unit):
                self.client.reset()
                self.store = ChromaVectorStore(self.client)
                self.service = IndexingService(self.embedder, self.store, parent_store=self.parents)
                result = ChunkingEngine(SMALL, WordCounter()).run(random_document(seed, unit=unit).document, CTX)
                self.service.index(result.children, document_uid=CTX.document_uid, parents=result.parents)

                col = self.client.get_collection(COLLECTION, embedding_function=None)
                got = col.get(include=["metadatas", "documents", "embeddings"])
                by_id = {vid: (doc, meta, emb) for vid, doc, meta, emb in
                         zip(got["ids"], got["documents"], got["metadatas"], got["embeddings"], strict=True)}

                self.assertEqual(set(by_id), {c.vector_id for c in result.children})
                for child in result.children:
                    doc, meta, emb = by_id[child.vector_id]
                    self.assertEqual(doc, child.text)
                    self.assertEqual(meta, child.chroma_metadata())
                    want = self.embedder.embed_documents([child.embedding_text])[0]
                    for a, b in zip(emb, want, strict=True):
                        self.assertAlmostEqual(float(a), b, places=5)

    def test_special_characters_survive_a_round_trip(self) -> None:
        nasty = 'quotes " \' backslash \\ newline\nTab\t emoji 😀 arabic مرحبا cjk 日本語 null-free <b>&amp;</b> 100% {braces}'
        blocks = [H(nasty), Pg((nasty + ". ") * 6)]
        result = ChunkingEngine(SMALL, WordCounter()).run(build(blocks), CTX)
        self.service.index(result.children, document_uid="doc-1", parents=result.parents)
        hit = self.store.query(COLLECTION, self.embedder.embed_query("quotes backslash emoji"),
                               user_id="u1", course_id="c1", k=1)[0]

        child = next(c for c in result.children if c.vector_id == hit.id)
        self.assertEqual(hit.document, child.text)
        self.assertEqual(hit.metadata["heading_path"], nasty)
        self.assertEqual(hit.metadata["citation_label"], child.citation_label)

    def test_very_long_text_and_metadata_values(self) -> None:
        self.store.upsert("big-test", [VectorRecord("d:0", [1.0, 0.0], "x" * 500_000,
                                                    {"document_uid": "d", "embedding_hash": "h", **SCOPE,
                                                     "heading_path": "H " * 20_000})])
        hit = self.store.query("big-test", [1.0, 0.0], k=1, **SCOPE)[0]

        self.assertEqual(len(hit.document), 500_000)
        self.assertEqual(len(str(hit.metadata["heading_path"])), 40_000)

    def test_scalar_types_are_preserved(self) -> None:
        result = ChunkingEngine(SMALL, WordCounter()).run(build([H("A"), Pg(sentences(3))]), CTX)
        self.service.index(result.children, document_uid="doc-1", parents=result.parents)
        meta = self.client.get_collection(COLLECTION, embedding_function=None).get(include=["metadatas"])["metadatas"][0]

        self.assertIsInstance(meta["page_number"], int)
        self.assertIsInstance(meta["confidence"], float)
        self.assertIsInstance(meta["low_confidence"], bool)
        self.assertIsInstance(meta["heading_path"], str)


class ScaleBoundaryTests(ChromaTestCase):
    def test_batch_limit_is_respected_with_a_real_oversize_upsert(self) -> None:
        limit = int(self.client.get_max_batch_size())
        records = [record(i, dim=3) for i in range(limit + 120)]
        self.store.upsert("batch-test", records)

        self.assertEqual(self.store.count("batch-test"), limit + 120)
        deleted = self.store.delete("batch-test", [r.id for r in records])
        self.assertEqual(deleted, limit + 120)
        self.assertEqual(self.store.count("batch-test"), 0)

    def test_list_ids_pages_through_more_than_one_page(self) -> None:
        self.store.upsert("page-test", [record(i, dim=3) for i in range(2350)])
        ids = self.store.list_ids("page-test", document_uid="d")

        self.assertEqual(len(ids), 2350)
        self.assertEqual(ids["d:2349"], "h2349")

    def test_k_larger_than_the_collection_and_filters_matching_nothing(self) -> None:
        self.store.upsert("small-test", [record(i) for i in range(3)])

        self.assertEqual(len(self.store.query("small-test", [1.0, 0.0, 0.0, 0.0], k=10_000, **SCOPE)), 3)
        self.assertEqual(self.store.query("small-test", [1.0, 0.0, 0.0, 0.0], k=5,
                                          filters={"kind": "none"}, **SCOPE), [])

    def test_results_are_ordered_by_score_then_id(self) -> None:
        same = [VectorRecord(f"d:{n}", [1.0, 0.0], "t", {"document_uid": "d", "embedding_hash": "h", **SCOPE})
                for n in ("c", "a", "b")]
        self.store.upsert("tie-test", same)
        hits = self.store.query("tie-test", [1.0, 0.0], k=3, **SCOPE)

        self.assertEqual([h.id for h in hits], ["d:a", "d:b", "d:c"])
        self.assertTrue(all(abs(h.score - 1.0) < 1e-5 for h in hits))

    def test_mixed_dimensions_in_one_collection_are_refused(self) -> None:
        self.store.upsert("dim-test", [record(0, dim=4)])
        with self.assertRaises(Exception):
            self.store.upsert("dim-test", [record(1, dim=7)])
        self.assertEqual(self.store.count("dim-test"), 1)


class ConcurrencyTests(ChromaTestCase):
    def test_parallel_writers_and_readers(self) -> None:
        errors: list[Exception] = []

        def writer(n: int) -> None:
            try:
                self.store.upsert("conc-test", [record(n * 100 + i, doc=f"w{n}", dim=4) for i in range(60)])
            except Exception as exc:
                errors.append(exc)

        def reader() -> None:
            try:
                for _ in range(20):
                    self.store.query("conc-test", [1.0, 0.0, 0.0, 0.0], k=5, **SCOPE)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(self.store.count("conc-test"), 360)
        for n in range(6):
            self.assertEqual(len(self.store.list_ids("conc-test", document_uid=f"w{n}")), 60)


class CollectionNamingTests(unittest.TestCase):
    """REG-10: collection names must always be valid for the database."""

    VALID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,510}[a-zA-Z0-9]$")

    def test_names_are_valid_for_awkward_model_ids(self) -> None:
        for model in ("BAAI/bge-small-en-v1.5", "org/My Model_v2+x", "///", "", "ünï/çödé 模型", "a" * 600,
                      "ns/model:latest", "model with spaces"):
            with self.subTest(model=model[:30]):
                name = collection_name(model)
                self.assertRegex(name, self.VALID)
                client = fresh_client()
                ChromaVectorStore(client).upsert(name, [record(0)])
                self.assertEqual(ChromaVectorStore(client).count(name), 1)

    def test_names_differ_per_model_and_chunker_major(self) -> None:
        self.assertNotEqual(collection_name("a/model-1"), collection_name("a/model-2"))
        self.assertNotEqual(collection_name("m", "1.4.0"), collection_name("m", "2.0.0"))
        self.assertEqual(collection_name("m", "1.4.0"), collection_name("m", "1.9.9"))
        self.assertNotEqual(collection_name("org/model a"), collection_name("org/model-a"))  # sanitised ids stay distinct
        self.assertEqual(collection_name("BAAI/bge-small-en-v1.5"), "chunks__bge-small-en-v1.5__c1")  # clean ids unchanged


if __name__ == "__main__":
    unittest.main()

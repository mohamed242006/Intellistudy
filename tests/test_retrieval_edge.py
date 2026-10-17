"""Retrieval: no-result paths, unrelated queries, duplicates, thresholds, multi-tenant fuzz.

(test_retrieval.py holds the main scenarios; this file is the adversarial counterpart.)
"""

from __future__ import annotations

import itertools
import random
import unittest

import chromadb
from chromadb.config import Settings

from ai.chunking import ChunkContext, ChunkingEngine, IndexingService
from ai.chunking.errors import EmbeddingError
from ai.chunking.memory_store import InMemoryParentStore, InMemoryVectorStore
from ai.retrieval import RetrievalService
from ai.storage import SQLiteParentStore
from ai.vectorstore import ChromaVectorStore
from tests.chunk_fixtures import SMALL, FakeEmbedder, H, Pg, WordCounter, build, sentences


def ctx(uid: str, user: str = "u1", course: str = "c1") -> ChunkContext:
    return ChunkContext(user_id=user, course_id=course, document_uid=uid, embedding_model="fake-embed")


class EdgeBase:
    def new_stores(self):
        return InMemoryVectorStore(), InMemoryParentStore()

    def setUp(self) -> None:
        self.embedder = FakeEmbedder(dimension=512)
        self.store, self.parents = self.new_stores()
        self.indexer = IndexingService(self.embedder, self.store, parent_store=self.parents)
        self.service = RetrievalService(self.embedder, self.store, self.parents)
        self.engine = ChunkingEngine(SMALL, WordCounter())

    def index(self, blocks, context):
        chunk_set = self.engine.run(build(blocks), context)
        self.indexer.index(chunk_set.children, document_uid=context.document_uid, parents=chunk_set.parents)
        return chunk_set

    def search(self, query, **kw):
        kw.setdefault("user_id", "u1")
        kw.setdefault("course_id", "c1")
        return self.service.search(query, **kw)


class NoResultTests(EdgeBase, unittest.TestCase):
    def test_every_empty_path_returns_an_empty_result_not_an_error(self) -> None:
        self.assertTrue(self.search("anything").is_empty)  # empty store
        self.index([H("A"), Pg("alpha beta gamma delta epsilon zeta eta theta.")], ctx("d1"))
        for kwargs in ({"user_id": "nobody"}, {"course_id": "nothing"}, {"document_uids": ["ghost"]},
                       {"document_uids": []}, {"filters": {"kind": "table"}},
                       {"filters": {"heading_top": "Nope"}}, {"min_score": 1.01}):
            with self.subTest(kwargs=kwargs):
                result = self.search("alpha beta", **kwargs)
                self.assertTrue(result.is_empty)
                self.assertEqual((result.hits, result.parents), ([], []))

    def test_k_larger_than_everything_returns_everything(self) -> None:
        self.index([H("A"), Pg(sentences(3))], ctx("d1"))

        self.assertEqual(len(self.search("w", k=10**6).hits), 1)

    def test_unrelated_query_scores_far_below_a_relevant_one(self) -> None:
        self.index([H("Caching"), Pg("lru cache eviction removes the least recently used entry now.")], ctx("d1"))
        relevant = self.search("lru cache eviction", k=1).hits[0].score
        unrelated = self.search("zzzz qqqq xxxx wwww", k=1).hits
        unrelated_score = unrelated[0].score if unrelated else 0.0

        self.assertGreater(relevant, 0.5)
        self.assertLess(unrelated_score, 0.3)  # fake hashed bag-of-words: collisions give small noise
        self.assertTrue(self.search("zzzz qqqq xxxx wwww", min_score=0.3).is_empty)


class ThresholdTests(EdgeBase, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.index([H("Caching"), Pg("lru cache eviction removes the least recently used entry now.")], ctx("d1"))

    def test_min_score_boundary_is_inclusive(self) -> None:
        score = self.search("lru cache eviction", k=1).hits[0].score

        self.assertFalse(self.search("lru cache eviction", min_score=score).is_empty)
        self.assertTrue(self.search("lru cache eviction", min_score=score + 1e-6).is_empty)

    def test_extreme_thresholds(self) -> None:
        self.assertFalse(self.search("lru cache", min_score=-5.0).is_empty)
        self.assertFalse(self.search("lru cache", min_score=0.0).is_empty)
        self.assertTrue(self.search("lru cache", min_score=2.0).is_empty)


class DuplicateTests(EdgeBase, unittest.TestCase):
    def test_identical_sections_inside_one_document_are_both_returned_with_distinct_ids(self) -> None:
        body = "repeated boilerplate sentence about the license terms and conditions here."
        self.index([H("Legal"), Pg(body), H("Appendix"), Pg(body)], ctx("d1"))
        hits = self.search("license terms conditions", k=5).hits

        self.assertEqual(len(hits), 2)
        self.assertEqual(len({h.chunk_id for h in hits}), 2)
        self.assertEqual(hits[0].text, hits[1].text)

    def test_ties_are_broken_deterministically(self) -> None:
        body = "identical text identical text identical text identical text."
        self.index([H("A"), Pg(body), H("B"), Pg(body), H("C"), Pg(body)], ctx("d1"))
        runs = [[h.chunk_id for h in self.search("identical text", k=5).hits] for _ in range(5)]

        self.assertTrue(all(r == runs[0] for r in runs))

    def test_same_file_for_two_users_is_returned_separately(self) -> None:
        blocks = [H("Shared"), Pg("the same lecture file uploaded by two different students today.")]
        self.index(blocks, ctx("d1", user="u1", course="c1"))
        self.index(blocks, ctx("d2", user="u2", course="c2"))
        first = self.search("same lecture file", k=5)
        second = self.search("same lecture file", k=5, user_id="u2", course_id="c2")

        self.assertEqual([h.document_uid for h in first.hits], ["d1"])
        self.assertEqual([h.document_uid for h in second.hits], ["d2"])
        self.assertEqual(first.hits[0].chunk_id, second.hits[0].chunk_id)
        self.assertEqual(first.parents[0].parent.user_id, "u1")
        self.assertEqual(second.parents[0].parent.user_id, "u2")


class QueryInputTests(EdgeBase, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.index([H("A"), Pg("alpha beta gamma delta epsilon zeta eta theta iota kappa.")], ctx("d1"))

    def test_unusual_but_valid_queries(self) -> None:
        for query in ("???", "!!!", "日本語のクエリ", "مرحبا بالعالم", "😀 🎉", "x" * 50_000, "a\nb\tc",
                      "'; DROP TABLE chunks; --", "{\"$ne\": 1}", "\u200b alpha", "alpha " * 5000):
            with self.subTest(query=query[:20]):
                result = self.search(query, k=3)
                self.assertIsInstance(result.hits, list)

    def test_blank_queries_are_rejected(self) -> None:
        for query in ("", "   ", "\n\t "):
            with self.subTest(query=repr(query)), self.assertRaises(ValueError):
                self.search(query)

    def test_wrong_dimension_query_embedding_is_an_error_not_a_wrong_answer(self) -> None:
        class Broken(FakeEmbedder):
            def embed_query(self, text):
                return [0.1, 0.2, 0.3]

        service = RetrievalService(Broken(dimension=512), self.store, self.parents)
        with self.assertRaises(EmbeddingError):
            service.search("alpha", user_id="u1", course_id="c1")

    def test_parameters_are_validated(self) -> None:
        for kwargs in ({"k": 0}, {"k": -3}, {"user_id": ""}, {"course_id": ""}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.search("alpha", **kwargs)
        with self.assertRaises(ValueError):
            self.search("alpha", filters={"user_id": "u2"})
        with self.assertRaises(ValueError):
            self.search("alpha", filters={"kind": {"$ne": "text"}})


class ParentExpansionEdgeTests(EdgeBase, unittest.TestCase):
    def test_budget_edge_values(self) -> None:
        self.index([H("A"), Pg(sentences(3)), H("B"), Pg(sentences(3, prefix="b"))], ctx("d1"))
        query = "s0_0 b0_0"

        self.assertEqual(len(self.search(query, k=5, parent_token_budget=0).parents), 1)  # best parent always kept
        self.assertEqual(len(self.search(query, k=5, parent_token_budget=10**9).parents), 2)

    def test_parent_cleared_from_store_mid_flight_is_reported(self) -> None:
        chunk_set = self.index([H("A"), Pg(sentences(3))], ctx("d1"))
        self.parents.delete([p.store_key for p in chunk_set.parents])
        result = self.search("s0_0")

        self.assertTrue(result.hits)
        self.assertEqual(result.parents, [])
        self.assertTrue(any("not found" in w for w in result.warnings))

    def test_hits_without_a_parent_reference_are_reported_not_crashed(self) -> None:
        chunk_set = self.index([H("A"), Pg(sentences(3))], ctx("d1"))
        vid = chunk_set.children[0].vector_id
        record = self.store._data[next(iter(self.store._data))][vid]
        object.__setattr__(record, "metadata", {**record.metadata, "parent_chunk_id": ""})
        result = self.search("s0_0")

        self.assertTrue(any("no parent_chunk_id" in w for w in result.warnings))


class MultiTenantFuzzTests(unittest.TestCase):
    """Property: whatever the query, results never leave the caller's (user, course)."""

    def stacks(self):
        yield "memory", InMemoryVectorStore(), InMemoryParentStore(), None
        client = chromadb.EphemeralClient(settings=Settings(allow_reset=True, anonymized_telemetry=False))
        client.reset()
        parents = SQLiteParentStore()
        self.addCleanup(client.reset)
        self.addCleanup(parents.close)
        yield "chroma", ChromaVectorStore(client), parents, client

    def test_results_are_always_scoped(self) -> None:
        users, courses = ("u1", "u2", "u3"), ("c1", "c2")
        rnd = random.Random(7)
        for name, store, parents, _ in self.stacks():
            with self.subTest(stack=name):
                embedder = FakeEmbedder(dimension=256)
                indexer = IndexingService(embedder, store, parent_store=parents)
                engine = ChunkingEngine(SMALL, WordCounter())
                expected: dict[tuple[str, str], set[str]] = {}
                for n, (user, course) in enumerate(itertools.product(users, courses)):
                    for d in range(2):  # every tenant uploads documents that share vocabulary
                        uid = f"doc-{user}-{course}-{d}"
                        blocks = [H(f"Topic {d}"), Pg(sentences(4, per=6, prefix="shared"))]
                        chunk_set = engine.run(build(blocks), ctx(uid, user, course))
                        indexer.index(chunk_set.children, document_uid=uid, parents=chunk_set.parents)
                        expected.setdefault((user, course), set()).add(uid)
                service = RetrievalService(embedder, store, parents)
                for _ in range(40):
                    user, course = rnd.choice(users), rnd.choice(courses)
                    result = service.search(f"shared{rnd.randint(0, 3)}_{rnd.randint(0, 5)} topic",
                                            user_id=user, course_id=course, k=rnd.randint(1, 9))
                    for hit in result.hits:
                        self.assertEqual((hit.user_id, hit.course_id), (user, course))
                        self.assertIn(hit.document_uid, expected[(user, course)])
                    for context in result.parents:
                        self.assertEqual((context.parent.user_id, context.parent.course_id), (user, course))
                        self.assertIn(context.parent.document_uid, expected[(user, course)])


if __name__ == "__main__":
    unittest.main()

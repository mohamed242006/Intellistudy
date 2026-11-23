"""E2E-10: bibliography ranking, reranking hook, and the relevance assessment (offline, fake models)."""

from __future__ import annotations

import dataclasses
import unittest
from collections.abc import Sequence

from ai.chunking.engine import ChunkingEngine
from ai.chunking.indexing import IndexingService
from ai.chunking.memory_store import InMemoryParentStore, InMemoryVectorStore
from ai.chunking.models import ChunkContext
from ai.retrieval import RetrievalService
from ai.retrieval.assessment import (
    NONE,
    STRONG,
    WEAK,
    RetrievalPolicy,
    assess,
    content_terms,
    lexical_coverage,
)
from ai.retrieval.models import RetrievedChunk
from ai.retrieval.references import asks_for_references, is_reference_section
from tests.chunk_fixtures import SMALL, FakeEmbedder, H, Pg, WordCounter, build

POLICY = RetrievalPolicy(
    version="test", strong_vector=0.6, weak_vector=0.3, strong_rerank=2.0, weak_rerank=-1.0,
    min_coverage_vector=0.5, min_coverage_rerank=0.5,
)


def hit(score: float, text: str = "body", path: tuple[str, ...] = (), rerank: float | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c", parent_chunk_id="p", score=score, text=text, kind="text", doc_id="d", document_uid="u",
        file_name="notes.pdf", heading_path=path, citation_label="p. 1", page_number=1, slide_number=None,
        block_types=("paragraph",), ocr_confidence=None, low_confidence=False, user_id="u1", course_id="c1",
        rerank_score=rerank,
    )


class ReferenceDetectionTests(unittest.TestCase):
    def test_heading_names_identify_bibliographies(self) -> None:
        for title in ("References", "REFERENCES", "7. Bibliography", "Works Cited", "Literature cited"):
            with self.subTest(title=title):
                self.assertTrue(is_reference_section(("Paper", title)))

    def test_ordinary_headings_are_not_bibliographies(self) -> None:
        for title in ("Introduction", "Reference frames", "Sources of error in measurement"):
            with self.subTest(title=title):
                self.assertFalse(is_reference_section(("Paper", title)))

    def test_numbered_entry_lists_are_bibliographies_even_without_a_heading(self) -> None:
        text = "[1] A. Smith, Rings, 1997.\n[2] B. Jones, Modules, 2001.\n[3] C. Lee, Ideals, 2010."
        self.assertTrue(is_reference_section((), text))
        self.assertFalse(is_reference_section((), "[1] see below\nThe proof follows.\nWe conclude here."))

    def test_query_intent_about_sources(self) -> None:
        for query in ("Who wrote the original RAG paper?", "list the references", "which papers cite Barucci", "journal of the article"):
            with self.subTest(query=query):
                self.assertTrue(asks_for_references(query))
        for query in ("What is a Gorenstein ring?", "How does the Playfair cipher work?"):
            with self.subTest(query=query):
                self.assertFalse(asks_for_references(query))


class RankingTests(unittest.TestCase):
    """The bibliography repeats the title words, so by similarity alone it beats the abstract."""

    def setUp(self) -> None:
        self.embedder = FakeEmbedder(dimension=512)
        self.store, self.parents = InMemoryVectorStore(), InMemoryParentStore()
        blocks = [
            H("Abstract"),
            Pg("we prove a structure theorem for almost gorenstein rings using local cohomology and graded modules."),
            H("References"),
            Pg("barucci froberg almost gorenstein rings algebra 1997. bruns herzog gorenstein rings cambridge. almost gorenstein rings."),
        ]
        chunks = ChunkingEngine(SMALL, WordCounter()).run(
            build(blocks), ChunkContext("u1", "c1", "doc-1", "fake-embed")
        )
        IndexingService(self.embedder, self.store, parent_store=self.parents).index(
            chunks.children, document_uid="doc-1", parents=chunks.parents
        )
        self.service = RetrievalService(self.embedder, self.store, self.parents, policy=POLICY)

    def search(self, query: str, **kwargs):
        return self.service.search(query, user_id="u1", course_id="c1", k=5, **kwargs)

    def test_reference_chunk_wins_by_similarity_alone(self) -> None:
        result = self.search("almost gorenstein rings", include_references=True)
        self.assertTrue(result.hits[0].is_reference)  # documents the problem E2E-10 describes

    def test_default_ranks_body_text_before_the_bibliography(self) -> None:
        result = self.search("almost gorenstein rings")
        self.assertFalse(result.hits[0].is_reference)
        self.assertTrue(result.hits[-1].is_reference)

    def test_queries_about_sources_keep_the_bibliography_first(self) -> None:
        result = self.search("references on almost gorenstein rings")
        self.assertTrue(result.hits[0].is_reference)

    def test_references_can_be_excluded(self) -> None:
        result = self.search("almost gorenstein rings", include_references=False)
        self.assertTrue(result.hits)
        self.assertFalse(any(h.is_reference for h in result.hits))

    def test_results_are_never_lost_by_demotion(self) -> None:
        default = {h.chunk_id for h in self.search("almost gorenstein rings").hits}
        untouched = {h.chunk_id for h in self.search("almost gorenstein rings", include_references=True).hits}
        self.assertEqual(default, untouched)


class FakeReranker:
    name = "fake-reranker"

    def __init__(self, scores: list[float] | None = None, fail: bool = False) -> None:
        self.scores, self.fail, self.calls = scores, fail, []

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        self.calls.append((query, list(passages)))
        if self.fail:
            raise RuntimeError("model unavailable")
        return self.scores if self.scores is not None else [float(len(p)) for p in passages]


class RerankTests(unittest.TestCase):
    def setUp(self) -> None:
        self.embedder = FakeEmbedder(dimension=512)
        self.store, self.parents = InMemoryVectorStore(), InMemoryParentStore()
        blocks = [
            H("Caching"), Pg("lru cache eviction removes the least recently used entry when the cache is full."),
            H("Networking"), Pg("tcp handshake uses syn and ack packets between the client and the server."),
            H("Databases"), Pg("sql join combines rows from two tables using a key and an index."),
        ]
        chunks = ChunkingEngine(SMALL, WordCounter()).run(build(blocks), ChunkContext("u1", "c1", "doc-1", "fake-embed"))
        IndexingService(self.embedder, self.store, parent_store=self.parents).index(
            chunks.children, document_uid="doc-1", parents=chunks.parents
        )

    def service(self, reranker) -> RetrievalService:
        return RetrievalService(self.embedder, self.store, self.parents, reranker=reranker, policy=POLICY)

    def test_reranker_reorders_and_scores_are_attached(self) -> None:
        by_len = self.service(FakeReranker()).search("cache eviction", user_id="u1", course_id="c1", k=3)
        longest = max(by_len.hits, key=lambda h: len(h.heading_path[-1] + h.text))
        self.assertEqual(by_len.hits[0].chunk_id, longest.chunk_id)
        self.assertTrue(all(h.rerank_score is not None for h in by_len.hits))
        self.assertGreaterEqual(by_len.hits[0].rerank_score, by_len.hits[-1].rerank_score)

    def test_passages_given_to_the_reranker_include_the_heading(self) -> None:
        reranker = FakeReranker()
        self.service(reranker).search("cache eviction", user_id="u1", course_id="c1", k=3)
        self.assertTrue(any(p.startswith("Caching\n") for p in reranker.calls[0][1]))

    def test_rerank_false_skips_the_model(self) -> None:
        reranker = FakeReranker()
        result = self.service(reranker).search("cache", user_id="u1", course_id="c1", rerank=False)
        self.assertEqual(reranker.calls, [])
        self.assertTrue(all(h.rerank_score is None for h in result.hits))

    def test_failing_reranker_degrades_to_vector_order_with_a_warning(self) -> None:
        result = self.service(FakeReranker(fail=True)).search("cache eviction", user_id="u1", course_id="c1", k=3)
        self.assertTrue(result.hits)
        self.assertTrue(any("reranker failed" in w for w in result.warnings))
        self.assertEqual(result.hits, sorted(result.hits, key=lambda h: -h.score))

    def test_wrong_number_of_scores_is_ignored(self) -> None:
        result = self.service(FakeReranker(scores=[1.0])).search("cache", user_id="u1", course_id="c1", k=3)
        self.assertTrue(any("different number of scores" in w for w in result.warnings))

    def test_min_score_still_filters_on_similarity_before_reranking(self) -> None:
        reranker = FakeReranker()
        result = self.service(reranker).search("zzzz qqqq", user_id="u1", course_id="c1", min_score=0.5)
        self.assertEqual(result.hits, [])
        self.assertEqual(reranker.calls, [])


class AssessmentTests(unittest.TestCase):
    def test_content_terms_drop_stopwords_and_stem(self) -> None:
        self.assertEqual(content_terms("What are the advantages of aspects?"), content_terms("advantages aspects"))
        self.assertEqual(content_terms("playfair ciphers"), content_terms("playfair cipher"))
        self.assertEqual(content_terms("what is the"), [])

    def test_coverage_counts_words_found_in_text_headings_or_file_name(self) -> None:
        hits = [hit(0.8, "the playfair cipher uses a grid", ("Classical ciphers",))]
        coverage, missing = lexical_coverage("playfair cipher tuition fee", hits)
        self.assertEqual(missing, ("tuition", "fee"))
        self.assertAlmostEqual(coverage, 0.5)
        self.assertEqual(lexical_coverage("notes", hits)[0], 1.0)  # file name counts

    def test_levels_follow_the_policy_thresholds_on_the_vector_score(self) -> None:
        for score, expected in ((0.7, STRONG), (0.4, WEAK), (0.2, NONE)):
            with self.subTest(score=score):
                self.assertEqual(assess("cache", [hit(score, "cache")], POLICY).level, expected)

    def test_reranker_score_takes_over_when_present(self) -> None:
        self.assertEqual(assess("cache", [hit(0.1, "cache", rerank=3.0)], POLICY).level, STRONG)
        self.assertEqual(assess("cache", [hit(0.9, "cache", rerank=-8.0)], POLICY).level, NONE)

    def test_missing_question_words_downgrade_one_level_and_are_reported(self) -> None:
        assessment = assess("tuition fee prices", [hit(0.8, "university overview")], POLICY)
        self.assertEqual(assessment.level, WEAK)
        self.assertEqual(assessment.missing_terms, ("tuition", "fee", "prices"))
        self.assertIn("coverage", " ".join(assessment.reasons))

    def test_no_hits_means_none(self) -> None:
        assessment = assess("anything", [], POLICY)
        self.assertEqual((assessment.level, assessment.answerable), (NONE, False))

    def test_search_attaches_the_assessment_unless_disabled(self) -> None:
        embedder = FakeEmbedder(dimension=512)
        store, parents = InMemoryVectorStore(), InMemoryParentStore()
        chunks = ChunkingEngine(SMALL, WordCounter()).run(
            build([H("Caching"), Pg("lru cache eviction removes the least recently used entry.")]),
            ChunkContext("u1", "c1", "doc-1", "fake-embed"),
        )
        IndexingService(embedder, store, parent_store=parents).index(chunks.children, document_uid="doc-1", parents=chunks.parents)
        service = RetrievalService(embedder, store, parents, policy=POLICY)

        with_it = service.search("lru cache eviction", user_id="u1", course_id="c1")
        without = service.search("lru cache eviction", user_id="u1", course_id="c1", assess_relevance=False)
        self.assertIsNotNone(with_it.assessment)
        self.assertEqual(with_it.assessment.policy_version, "test")
        self.assertIsNone(without.assessment)


class PolicyGuardTests(unittest.TestCase):
    """Scores of different models are not comparable: a mismatching policy must not be applied silently."""

    def setUp(self) -> None:
        self.embedder = FakeEmbedder(dimension=512)
        store, parents = InMemoryVectorStore(), InMemoryParentStore()
        chunks = ChunkingEngine(SMALL, WordCounter()).run(
            build([H("Caching"), Pg("lru cache eviction removes the least recently used entry.")]),
            ChunkContext("u1", "c1", "doc-1", "fake-embed"),
        )
        IndexingService(self.embedder, store, parent_store=parents).index(
            chunks.children, document_uid="doc-1", parents=chunks.parents
        )
        self.store, self.parents = store, parents

    def search(self, policy: RetrievalPolicy, reranker=None):
        service = RetrievalService(self.embedder, self.store, self.parents, reranker=reranker, policy=policy)
        return service.search("lru cache eviction", user_id="u1", course_id="c1")

    def test_builtin_policy_is_not_applied_to_a_model_it_was_not_measured_with(self) -> None:
        service = RetrievalService(self.embedder, self.store, self.parents)  # default policy, fake embedder
        result = service.search("lru cache eviction", user_id="u1", course_id="c1")
        self.assertIsNone(result.assessment)
        self.assertEqual(result.warnings, [])

    def test_forcing_the_assessment_on_a_foreign_model_warns(self) -> None:
        service = RetrievalService(self.embedder, self.store, self.parents)
        result = service.search("lru cache eviction", user_id="u1", course_id="c1", assess_relevance=True)
        self.assertIsNotNone(result.assessment)
        self.assertTrue(any("calibrated for BAAI/bge-small-en-v1.5" in w for w in result.warnings))

    def test_matching_models_produce_no_warning(self) -> None:
        policy = dataclasses.replace(POLICY, embedding_model="fake-embed", reranker_model="fake-reranker")
        result = self.search(policy, FakeReranker(scores=[5.0]))
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.assessment.level, STRONG)

    def test_embedder_mismatch_is_reported(self) -> None:
        policy = dataclasses.replace(POLICY, embedding_model="some-other-embedder")
        result = self.search(policy)
        self.assertTrue(any("calibrated for some-other-embedder" in w for w in result.warnings))

    def test_reranker_mismatch_falls_back_to_vector_thresholds(self) -> None:
        policy = dataclasses.replace(POLICY, reranker_model="the-calibrated-one")
        result = self.search(policy, FakeReranker(scores=[-50.0]))  # absurdly low on the foreign scale
        self.assertTrue(any("using vector scores only" in w for w in result.warnings))
        self.assertNotEqual(result.assessment.level, NONE)  # the foreign score was ignored
        self.assertIn("vector", result.assessment.reasons[0])


class CrossEncoderWrapperTests(unittest.TestCase):
    """The real model is not loaded in unit tests: a stand-in checks how the wrapper drives it."""

    def test_model_is_loaded_lazily_once_and_pairs_are_truncated_and_batched(self) -> None:
        from unittest import mock

        from ai.retrieval.rerank import CrossEncoderReranker

        created: list[tuple] = []
        predicted: list[tuple] = []

        class FakeCrossEncoder:
            def __init__(self, name: str, max_length: int, device: str | None) -> None:
                created.append((name, max_length, device))

            def predict(self, pairs, batch_size, show_progress_bar):
                predicted.append((list(pairs), batch_size, show_progress_bar))
                return [float(len(p)) for _, p in pairs]

        with mock.patch("sentence_transformers.CrossEncoder", FakeCrossEncoder):
            reranker = CrossEncoderReranker("some/model", batch_size=4)
            self.assertEqual(created, [])  # nothing loaded at construction
            self.assertEqual(reranker.score("q", []), [])
            self.assertEqual(created, [])  # and nothing for an empty request
            scores = reranker.score("q", ["short", "x" * 9000])
            reranker.score("q", ["again"])

        self.assertEqual(created, [("some/model", 512, None)])  # one load
        pairs, batch_size, progress = predicted[0]
        self.assertEqual((batch_size, progress), (4, False))
        self.assertEqual(scores, [5.0, 2500.0])  # the long passage was cut to 2500 characters
        self.assertEqual(pairs[0], ("q", "short"))


if __name__ == "__main__":
    unittest.main()

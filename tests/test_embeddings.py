"""Embeddings: generation, failure handling, cache reuse, hash stability, dimension checks.

Complements test_bge_embedder.py (BGE conventions) with failure injection and the
indexing-side guarantees: a bad embedder must never poison the index.
"""

from __future__ import annotations

import os
import unicodedata
import unittest

import numpy as np

from ai.chunking import (
    ApproxTokenCounter,
    ChunkConfig,
    ChunkingEngine,
    IndexingService,
    InMemoryVectorStore,
    default_token_counter,
)
from ai.chunking.errors import EmbeddingError, IndexingError
from ai.chunking.ids import content_hash, make_chunk_id, normalize_for_hash, vector_id
from ai.chunking.memory_store import InMemoryParentStore
from ai.chunking.text import TextSplitter
from ai.embedding import BgeEmbedder
from tests.chunk_fixtures import CTX, SMALL, FakeEmbedder, H, Pg, WordCounter, build, sentences

COLLECTION = "chunks__fake-embed__c1"


def chunks_for(*sections, config=SMALL, ctx=CTX):
    blocks = [b for section in sections for b in section]
    return ChunkingEngine(config, WordCounter()).run(build(blocks), ctx)


def section(title: str, prefix: str, n: int = 3):
    return [H(title), Pg(sentences(n, per=8, prefix=prefix))]


class StubModel:
    """Minimal SentenceTransformer stand-in that returns whatever matrix it is given."""

    def __init__(self, matrix_fn):
        self.matrix_fn = matrix_fn
        self.max_seq_length = 512

    def encode(self, texts, **kwargs):
        return self.matrix_fn(len(texts))


class BadModelOutputTests(unittest.TestCase):
    """REG-05: NaN / infinite / zero vectors must be rejected at the source."""

    def embedder(self, fn) -> BgeEmbedder:
        return BgeEmbedder(model=StubModel(fn))

    def test_nan_infinite_and_zero_vectors_are_rejected(self) -> None:
        cases = {
            "nan": lambda n: np.full((n, 384), np.nan),
            "inf": lambda n: np.full((n, 384), np.inf),
            "neg-inf": lambda n: np.full((n, 384), -np.inf),
            "zero": lambda n: np.zeros((n, 384)),
        }
        for name, fn in cases.items():
            with self.subTest(case=name), self.assertRaises(EmbeddingError):
                self.embedder(fn).embed_documents(["text"])

    def test_one_bad_row_in_a_batch_rejects_the_batch(self) -> None:
        def fn(n):
            good = np.ones((n, 384))
            good[n - 1] = np.nan
            return good

        with self.assertRaises(EmbeddingError):
            self.embedder(fn).embed_documents(["a", "b", "c"])

    def test_wrong_row_count_and_wrong_dimension(self) -> None:
        with self.assertRaises(EmbeddingError):
            self.embedder(lambda n: np.ones((n + 1, 384))).embed_documents(["a"])
        with self.assertRaises(EmbeddingError):
            self.embedder(lambda n: np.ones((n, 383))).embed_query("q")

    def test_valid_output_is_plain_python_floats(self) -> None:
        vectors = self.embedder(lambda n: np.ones((n, 384), dtype=np.float32)).embed_documents(["a", "b"])

        self.assertIsInstance(vectors, list)
        self.assertTrue(all(isinstance(x, float) for row in vectors for x in row))


class ModelLoadingFailureTests(unittest.TestCase):
    def test_loader_failure_propagates_and_is_retried_on_the_next_call(self) -> None:
        calls = {"n": 0}

        def flaky_loader(name, device):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("weights unavailable")
            return StubModel(lambda n: np.ones((n, 384)))

        embedder = BgeEmbedder(loader=flaky_loader)
        with self.assertRaises(OSError):
            embedder.embed_documents(["a"])
        self.assertFalse(embedder.loaded)
        self.assertEqual(len(embedder.embed_documents(["a"])[0]), 384)  # second attempt succeeds
        self.assertEqual(calls["n"], 2)

    def test_model_without_encode_is_an_error_not_a_hang(self) -> None:
        with self.assertRaises(AttributeError):
            BgeEmbedder(model=object()).embed_documents(["a"])

    def test_missing_dependency_message_is_actionable(self) -> None:
        def loader(name, device):
            raise ImportError("No module named 'sentence_transformers'")

        with self.assertRaisesRegex(ImportError, "sentence_transformers"):
            BgeEmbedder(loader=loader).embed_query("q")

    def test_indexing_service_does_not_swallow_model_failures(self) -> None:
        class Down(FakeEmbedder):
            def embed_documents(self, texts):
                raise ConnectionError("embedding server down")

        store = InMemoryVectorStore()
        with self.assertRaises(ConnectionError):
            IndexingService(Down(), store).index(chunks_for(section("A", "a")).children, document_uid="doc-1")
        self.assertEqual(store.count(COLLECTION), 0)


class PoisonedIndexTests(unittest.TestCase):
    """A misbehaving custom Embedder must not be able to corrupt the vector store."""

    def run_with(self, vectors_fn):
        class Evil(FakeEmbedder):
            def embed_documents(self, texts):
                return vectors_fn(texts, self.dimension)

        store = InMemoryVectorStore()
        service = IndexingService(Evil(), store)
        return service, store

    def test_rejects_nan_inf_zero_wrong_count_and_wrong_dimension(self) -> None:
        bad = {
            "nan": lambda t, d: [[float("nan")] * d for _ in t],
            "inf": lambda t, d: [[float("inf")] * d for _ in t],
            "zero": lambda t, d: [[0.0] * d for _ in t],
            "short": lambda t, d: [[0.1] * (d - 1) for _ in t],
            "count": lambda t, d: [[0.1] * d],
        }
        chunks = chunks_for(section("A", "a"), section("B", "b")).children
        for name, fn in bad.items():
            with self.subTest(case=name):
                service, store = self.run_with(fn)
                with self.assertRaises(IndexingError):
                    service.index(chunks, document_uid="doc-1")
                self.assertEqual(store.count(COLLECTION), 0)

    def test_failure_in_a_later_batch_leaves_the_existing_index_untouched(self) -> None:
        store = InMemoryVectorStore()
        good = FakeEmbedder()
        IndexingService(good, store).index(chunks_for(section("A", "a")).children, document_uid="doc-1")
        before = dict(store.list_ids(COLLECTION, document_uid="doc-1"))

        class FailsOnSecondBatch(FakeEmbedder):
            def embed_documents(self, texts):
                if self.document_calls >= 1:
                    raise RuntimeError("out of memory")
                return super().embed_documents(texts)

        service = IndexingService(FailsOnSecondBatch(), store, batch_size=1)
        changed = chunks_for(section("A", "a"), section("B", "b"), section("C", "c")).children
        with self.assertRaises(RuntimeError):
            service.index(changed, document_uid="doc-1")
        self.assertEqual(store.list_ids(COLLECTION, document_uid="doc-1"), before)


class EmbeddingReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.embedder = FakeEmbedder()
        self.store = InMemoryVectorStore()
        self.service = IndexingService(self.embedder, self.store, parent_store=InMemoryParentStore())

    def index(self, result):
        return self.service.index(result.children, document_uid="doc-1", parents=result.parents)

    def test_identical_text_is_embedded_once_per_call(self) -> None:
        repeated = [H("Boilerplate"), Pg(sentences(3, per=8, prefix="same"))]
        result = chunks_for(repeated, [H("Boilerplate"), Pg(sentences(3, per=8, prefix="same"))])
        report = self.index(result)

        self.assertEqual(len(result.children), 2)
        self.assertEqual(len(self.embedder.texts_embedded), 1)  # same embedding_text -> one model call
        self.assertEqual(report.embedded, 2)  # but both chunks are stored
        self.assertEqual(self.store.count(COLLECTION), 2)

    def test_reuse_when_chunking_parameters_change_but_texts_do_not(self) -> None:
        sections = [section(f"S{i}", f"s{i}") for i in range(4)]
        self.index(chunks_for(*sections))
        before = len(self.embedder.texts_embedded)
        other = ChunkConfig(target_tokens=45, max_tokens=66, min_tokens=11, overlap_tokens=9,
                            slide_min_body_tokens=3, table_max_tokens=45, context_max_tokens=12,
                            parent_max_tokens=130, prefix_max_tokens=12)
        report = self.index(chunks_for(*sections, config=other))

        self.assertEqual(report.embedded, 0)  # identical embedding text -> nothing re-embedded
        self.assertEqual(len(self.embedder.texts_embedded), before)

    def test_edited_heading_changes_the_embedding_even_if_the_text_is_unchanged(self) -> None:
        self.index(chunks_for(section("Caching", "a")))
        before = len(self.embedder.texts_embedded)
        report = self.index(chunks_for(section("Cache policies", "a")))

        self.assertEqual(report.embedded, 1)  # the heading is part of what is embedded
        self.assertEqual(len(self.embedder.texts_embedded) - before, 1)

    def test_missing_stored_vector_falls_back_to_embedding(self) -> None:
        class Forgetful(InMemoryVectorStore):
            def get_embeddings(self, collection, ids):
                return {}

        store = Forgetful()
        service = IndexingService(self.embedder, store)
        old = chunks_for(section("A", "a"), section("B", "b"))
        service.index(old.children, document_uid="doc-1")
        shifted = chunks_for(section("New", "n"), section("A", "a"), section("B", "b"))
        report = service.index(shifted.children, document_uid="doc-1")

        self.assertEqual(report.reused, 0)
        self.assertEqual(report.embedded, 3)
        self.assertEqual(set(store.list_ids(COLLECTION, document_uid="doc-1")),
                         {c.vector_id for c in shifted.children})


class HashStabilityTests(unittest.TestCase):
    def test_golden_values_catch_accidental_algorithm_changes(self) -> None:
        self.assertEqual(content_hash("hello world"), "2aae6c35c94fcfb4")  # sha1("hello world")[:16]
        self.assertEqual(make_chunk_id("2aae6c35c94fcfb4"), "c-2aae6c35c94f")
        self.assertEqual(make_chunk_id("2aae6c35c94fcfb4", 2), "c-2aae6c35c94f.2")
        self.assertEqual(vector_id("uid", "chunk"), "uid:chunk")

    def test_whitespace_and_unicode_normalisation(self) -> None:
        composed, decomposed = "café", unicodedata.normalize("NFD", "café")

        self.assertEqual(content_hash(composed), content_hash(decomposed))
        self.assertEqual(content_hash("a  b\n\tc"), content_hash("a b c"))
        self.assertEqual(content_hash("  padded  "), content_hash("padded"))
        self.assertNotEqual(content_hash("Case"), content_hash("case"))
        self.assertNotEqual(content_hash("a b"), content_hash("ab"))
        self.assertEqual(normalize_for_hash("a\u00a0b"), "a b")

    def test_hashes_are_hex_of_fixed_length(self) -> None:
        for text in ("", "x", "日本語", "😀" * 1000, "a" * 100_000):
            value = content_hash(text)
            self.assertRegex(value, r"^[0-9a-f]{16}$")

    def test_chunk_ids_change_only_when_the_chunk_changes(self) -> None:
        base = chunks_for(section("A", "a"), section("B", "b"), section("C", "c")).children
        edited = chunks_for(section("A", "a"), section("B", "bX"), section("C", "c")).children

        self.assertEqual([c.chunk_id for c in base][0], [c.chunk_id for c in edited][0])
        self.assertNotEqual([c.chunk_id for c in base][1], [c.chunk_id for c in edited][1])
        self.assertEqual([c.chunk_id for c in base][2], [c.chunk_id for c in edited][2])

    def test_embedding_hash_tracks_embedding_text_not_text(self) -> None:
        a = chunks_for(section("Caching", "a")).children[0]
        b = chunks_for(section("Other title", "a")).children[0]

        self.assertEqual(a.content_hash, b.content_hash)
        self.assertNotEqual(a.embedding_hash, b.embedding_hash)


class DimensionAndCollectionTests(unittest.TestCase):
    def test_embedder_and_chunk_model_names_must_agree(self) -> None:
        result = chunks_for(section("A", "a"))
        service = IndexingService(FakeEmbedder(model_name="other-model"), InMemoryVectorStore())

        with self.assertRaises(IndexingError):
            service.index(result.children, document_uid="doc-1")

    def test_different_models_never_share_a_collection(self) -> None:
        store = InMemoryVectorStore()
        small, big = FakeEmbedder("model-a", 8), FakeEmbedder("model-b", 32)
        ctx_a = CTX.__class__("u1", "c1", "doc-1", "model-a")
        ctx_b = CTX.__class__("u1", "c1", "doc-1", "model-b")
        IndexingService(small, store).index(chunks_for(section("A", "a"), ctx=ctx_a).children, document_uid="doc-1")
        IndexingService(big, store).index(chunks_for(section("A", "a"), ctx=ctx_b).children, document_uid="doc-1")

        self.assertEqual(store.count("chunks__model-a__c1"), 1)
        self.assertEqual(store.count("chunks__model-b__c1"), 1)

    def test_query_dimension_mismatch_is_detected_by_the_store(self) -> None:
        store = InMemoryVectorStore()
        IndexingService(FakeEmbedder(), store).index(chunks_for(section("A", "a")).children, document_uid="doc-1")

        with self.assertRaises(ValueError):
            store.query(COLLECTION, [0.1] * 3, user_id="u1", course_id="c1", k=1)


class TokenCounterTests(unittest.TestCase):
    def test_approximate_counter(self) -> None:
        counter = ApproxTokenCounter()

        self.assertEqual((counter.count(""), counter.count("abcd"), counter.count("abcde")), (0, 1, 2))
        self.assertEqual(counter.name, "approx-char4")

    def test_default_counter_falls_back_when_the_tokenizer_is_unavailable(self) -> None:
        from unittest import mock

        with mock.patch("ai.chunking.tokens.HFTokenCounter", side_effect=OSError("offline")):
            self.assertIsInstance(default_token_counter(), ApproxTokenCounter)

    @unittest.skipUnless(os.environ.get("INTELLISTUDY_MODEL_TESTS") == "1", "set INTELLISTUDY_MODEL_TESTS=1")
    def test_real_tokenizer_keeps_every_chunk_inside_the_model_window(self) -> None:
        counter = default_token_counter()
        blocks = [H("Title"), Pg(sentences(400, per=14)), H("Other"), Pg(" ".join(f"term{i}-x{i}" for i in range(3000)))]
        chunks = ChunkingEngine(tokenizer=counter, strict=True).chunk(build(blocks), CTX)

        self.assertTrue(counter.name.startswith("hf:"))
        self.assertLessEqual(max(c.token_count for c in chunks), 480)
        self.assertLess(480, 512)  # leaves room for [CLS]/[SEP]


class TextSplitterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.splitter = TextSplitter(WordCounter())

    def test_sentence_boundaries_including_arabic_question_mark_and_semicolons(self) -> None:
        text = "First sentence. Second one? Third!\nNew line item; semicolon part؟ Arabic mark"

        self.assertEqual(len(self.splitter.sentences(text)), 6)

    def test_pieces_never_exceed_the_limit_and_lose_nothing(self) -> None:
        text = " ".join(f"w{i}" for i in range(1000))
        pieces = self.splitter.split(text, 37)

        self.assertTrue(all(len(p.split()) <= 37 for p in pieces))
        self.assertEqual(" ".join(pieces).split(), text.split())

    def test_degenerate_inputs(self) -> None:
        self.assertEqual(self.splitter.split("", 10), [])
        self.assertEqual(self.splitter.split("   ", 10), [])
        self.assertEqual(self.splitter.split("one", 1), ["one"])
        self.assertEqual(self.splitter.tail("", 10), "")
        self.assertEqual(self.splitter.tail("A sentence here.", 0), "")

    def test_tail_returns_whole_trailing_sentences_within_budget(self) -> None:
        text = "One two three. Four five. Six seven eight nine."

        self.assertEqual(self.splitter.tail(text, 2), "")  # last sentence is 4 tokens
        self.assertEqual(self.splitter.tail(text, 4), "Six seven eight nine.")
        self.assertEqual(self.splitter.tail(text, 6), "Four five. Six seven eight nine.")

    def test_unbreakable_token_is_cut_by_characters(self) -> None:
        """REG-11: a base64 blob / long URL without spaces used to produce an oversize chunk."""
        counter = ApproxTokenCounter()
        splitter = TextSplitter(counter)
        blob = "A" * 40_000  # ~10,000 tokens, no whitespace
        pieces = splitter.split("Intro sentence. " + blob + " Outro sentence.", 400)

        self.assertTrue(all(counter.count(p) <= 400 for p in pieces))
        self.assertEqual("".join(pieces).replace(" ", ""), ("Introsentence." + blob + "Outrosentence."))


if __name__ == "__main__":
    unittest.main()

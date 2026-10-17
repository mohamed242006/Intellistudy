"""BgeEmbedder: conventions, replaceability, and (opt-in) the real model.

The real-model tests need torch + the cached/downloadable BGE weights, so they only run
when ``INTELLISTUDY_MODEL_TESTS=1``.
"""

from __future__ import annotations

import math
import os
import unittest

import numpy as np

from ai.chunking.config import EMBEDDING_DIM, EMBEDDING_MODEL, QUERY_INSTRUCTION
from ai.chunking.errors import EmbeddingError, IndexingError
from ai.chunking.interfaces import Embedder
from ai.embedding import BgeEmbedder


class FakeModel:
    """Stands in for a SentenceTransformer: records calls, returns unit vectors."""

    def __init__(self, dim: int = EMBEDDING_DIM) -> None:
        self.dim = dim
        self.calls: list[dict] = []
        self.max_seq_length = 512

    def get_sentence_embedding_dimension(self) -> int:
        return self.dim

    def encode(self, texts, **kwargs):
        self.calls.append({"texts": list(texts), **kwargs})
        rows = []
        for text in texts:
            vec = np.zeros(self.dim)
            vec[hash(text) % self.dim] = 1.0
            rows.append(vec)
        return np.array(rows)


class ConventionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = FakeModel()
        self.embedder = BgeEmbedder(model=self.model, batch_size=8)

    def test_defaults_target_bge_small(self) -> None:
        self.assertEqual(BgeEmbedder().model_name, "BAAI/bge-small-en-v1.5")
        self.assertEqual(BgeEmbedder().dimension, 384)
        self.assertEqual(EMBEDDING_MODEL, "BAAI/bge-small-en-v1.5")

    def test_satisfies_the_embedder_protocol(self) -> None:
        self.assertIsInstance(self.embedder, Embedder)

    def test_documents_are_embedded_without_instruction_and_normalised(self) -> None:
        vectors = self.embedder.embed_documents(["first passage", "second passage"])
        call = self.model.calls[0]

        self.assertEqual(call["texts"], ["first passage", "second passage"])  # no instruction
        self.assertTrue(call["normalize_embeddings"])
        self.assertEqual(call["batch_size"], 8)
        self.assertEqual(len(vectors), 2)
        self.assertTrue(all(len(v) == EMBEDDING_DIM for v in vectors))
        self.assertIsInstance(vectors[0], list)
        self.assertIsInstance(vectors[0][0], float)

    def test_queries_get_the_retrieval_instruction(self) -> None:
        self.embedder.embed_query("what is LRU?")

        self.assertEqual(self.model.calls[0]["texts"], [QUERY_INSTRUCTION + "what is LRU?"])

    def test_empty_inputs(self) -> None:
        self.assertEqual(self.embedder.embed_documents([]), [])
        self.assertEqual(self.model.calls, [])
        for blank in ("", "   "):
            with self.assertRaises(ValueError):
                self.embedder.embed_query(blank)

    def test_wrong_dimension_is_an_error(self) -> None:
        wrong = BgeEmbedder(model=FakeModel(dim=10))

        with self.assertRaises(EmbeddingError):
            wrong.embed_documents(["x"])
        self.assertTrue(issubclass(EmbeddingError, IndexingError))

    def test_batch_size_is_validated(self) -> None:
        with self.assertRaises(ValueError):
            BgeEmbedder(batch_size=0)


class LazyLoadingTests(unittest.TestCase):
    def test_nothing_is_loaded_until_first_use(self) -> None:
        loaded: list[tuple] = []

        def loader(name, device):
            loaded.append((name, device))
            return FakeModel()

        embedder = BgeEmbedder(loader=loader, device="cpu")
        self.assertFalse(embedder.loaded)
        self.assertEqual(loaded, [])

        embedder.embed_documents(["a"])
        embedder.embed_query("b")
        self.assertTrue(embedder.loaded)
        self.assertEqual(loaded, [("BAAI/bge-small-en-v1.5", "cpu")])  # loaded exactly once

    def test_model_dimension_is_verified_on_load(self) -> None:
        embedder = BgeEmbedder(loader=lambda name, device: FakeModel(dim=768))

        with self.assertRaises(EmbeddingError):
            embedder.embed_documents(["a"])

    def test_sequence_length_is_capped_at_the_model_window(self) -> None:
        model = FakeModel()
        model.max_seq_length = 8192
        BgeEmbedder(loader=lambda n, d: model).embed_documents(["a"])

        self.assertEqual(model.max_seq_length, 512)

    def test_is_replaceable_by_another_model(self) -> None:
        other = BgeEmbedder("BAAI/bge-base-en-v1.5", dimension=768, model=FakeModel(dim=768))

        self.assertEqual(len(other.embed_query("q")), 768)
        self.assertEqual(other.model_name, "BAAI/bge-base-en-v1.5")


@unittest.skipUnless(os.environ.get("INTELLISTUDY_MODEL_TESTS") == "1", "set INTELLISTUDY_MODEL_TESTS=1")
class RealModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.embedder = BgeEmbedder()

    def test_vectors_have_the_right_shape_and_are_unit_length(self) -> None:
        vectors = self.embedder.embed_documents(["Deadlocks occur when processes wait forever."])

        self.assertEqual(len(vectors[0]), 384)
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in vectors[0])), 1.0, places=3)

    def test_semantically_related_text_ranks_first(self) -> None:
        passages = [
            "LRU cache eviction removes the least recently used entry when the cache is full.",
            "The TCP three-way handshake uses SYN, SYN-ACK and ACK packets.",
            "Photosynthesis converts light energy into chemical energy in plants.",
        ]
        docs = self.embedder.embed_documents(passages)
        query = self.embedder.embed_query("How does a cache decide which entry to evict?")
        scores = [sum(q * d for q, d in zip(query, doc)) for doc in docs]

        self.assertEqual(scores.index(max(scores)), 0)

    def test_query_and_document_embeddings_differ_for_the_same_text(self) -> None:
        text = "virtual memory paging"

        self.assertNotEqual(self.embedder.embed_query(text), self.embedder.embed_documents([text])[0])


if __name__ == "__main__":
    unittest.main()

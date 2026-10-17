"""BgeEmbedder: ``BAAI/bge-small-en-v1.5`` behind the :class:`ai.chunking.Embedder` protocol.

BGE conventions implemented here (and nowhere else):

* **documents** are embedded as they are, with no instruction;
* **queries** are prefixed with the retrieval instruction;
* vectors are L2-normalised, so cosine similarity equals the dot product.

The model is loaded lazily on first use, so importing this module (and constructing the
embedder) is cheap and needs neither torch nor network. Anything with an ``encode``
method can be injected as ``model``, which keeps the class easy to test and replace.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from typing import Any

from ai.chunking.config import EMBEDDING_DIM, EMBEDDING_MODEL, MODEL_MAX_TOKENS, QUERY_INSTRUCTION
from ai.chunking.errors import EmbeddingError

logger = logging.getLogger(__name__)


class BgeEmbedder:
    """Sentence-Transformers implementation of the ``Embedder`` protocol.

    Args:
        model_name: Hugging Face model id; any BGE-style model works (set ``dimension``).
        dimension: expected vector size (384 for bge-small-en-v1.5), verified on load/encode.
        batch_size: texts per forward pass.
        device: ``"cpu"``, ``"cuda"`` ... or ``None`` for the library default.
        query_instruction: prefix added to queries only.
        model: an already-built object with ``encode(...)`` (skips loading; for tests/reuse).
        loader: factory used instead of ``SentenceTransformer`` when loading lazily.
    """

    def __init__(
        self,
        model_name: str = EMBEDDING_MODEL,
        *,
        dimension: int = EMBEDDING_DIM,
        batch_size: int = 32,
        device: str | None = None,
        query_instruction: str = QUERY_INSTRUCTION,
        model: Any | None = None,
        loader: Callable[[str, str | None], Any] | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self.model_name = model_name
        self.dimension = dimension
        self.batch_size = batch_size
        self.device = device
        self.query_instruction = query_instruction
        self._model = model
        self._loader = loader

    # ---------------------------------------------------------------- loading
    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def model(self) -> Any:
        if self._model is None:
            self._model = self._load()
        return self._model

    def _load(self) -> Any:
        logger.info("Loading embedding model %s", self.model_name)
        if self._loader is not None:
            model = self._loader(self.model_name, self.device)
        else:
            from sentence_transformers import SentenceTransformer  # lazy: heavy import

            model = SentenceTransformer(self.model_name, device=self.device)
        size = getattr(model, "get_sentence_embedding_dimension", lambda: None)()
        if size is not None and size != self.dimension:
            raise EmbeddingError(
                f"{self.model_name} produces {size}-d vectors, expected {self.dimension}"
            )
        if hasattr(model, "max_seq_length"):
            model.max_seq_length = min(int(model.max_seq_length or MODEL_MAX_TOKENS), MODEL_MAX_TOKENS)
        return model

    # -------------------------------------------------------------------- API
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passages (no instruction). Empty input returns an empty list."""
        if not texts:
            return []
        return self._encode(list(texts))

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query, with the BGE retrieval instruction."""
        if not text or not text.strip():
            raise ValueError("query must not be empty")
        return self._encode([self.query_instruction + text])[0]

    # ---------------------------------------------------------------- helpers
    def _encode(self, texts: list[str]) -> list[list[float]]:
        raw = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        vectors = [[float(x) for x in row] for row in raw]
        if len(vectors) != len(texts):
            raise EmbeddingError(f"model returned {len(vectors)} vectors for {len(texts)} texts")
        for vector in vectors:
            if len(vector) != self.dimension:
                raise EmbeddingError(
                    f"{self.model_name} returned a {len(vector)}-d vector, expected {self.dimension}"
                )
            if not all(math.isfinite(x) for x in vector):
                raise EmbeddingError(f"{self.model_name} returned NaN or infinite values")
            if not any(vector):
                raise EmbeddingError(f"{self.model_name} returned an all-zero vector")
        return vectors

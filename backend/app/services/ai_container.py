"""Process-wide AI services, created lazily on first use and shared by requests and jobs.

The API process owns the vector store and the parent store (Chroma's embedded mode is single-process). Backend code
reaches them only through this container and the service layer; nothing else imports ``chromadb`` (contract VEC-03,
checked statically by ``backend/tests/test_static_rules.py``).

Heavy imports (sentence-transformers, torch, chromadb) happen inside the factory methods, so importing the app, running
the test suite or calling ``/health`` does not load any model.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.app.core.config import Settings
from backend.app.providers import build_provider
from backend.app.providers.openai_compatible import OpenAICompatibleProvider

if TYPE_CHECKING:
    from ai.chunking.interfaces import Embedder, ParentStore, VectorStore
    from ai.retrieval import RetrievalService


class AIContainer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._embedder: Embedder | None = None
        self._reranker: Any = None
        self._vector_store: VectorStore | None = None
        self._parent_store: ParentStore | None = None
        self._retrieval: RetrievalService | None = None
        self._provider: OpenAICompatibleProvider | None = build_provider(settings)

    # ---------------------------------------------------------------------------------------------- status
    @property
    def provider(self) -> OpenAICompatibleProvider | None:
        return self._provider

    def status(self) -> dict[str, bool]:
        """Booleans only (SEC-08): never paths, keys or versions."""
        return {
            "embedder_loaded": self._embedder is not None,
            "reranker_loaded": self._reranker is not None,
            "vector_store_open": self._vector_store is not None,
        }

    # ------------------------------------------------------------------------------------------- factories
    @property
    def index_dir(self) -> Path:
        return self._settings.data_dir / "index"

    def embedder(self) -> Embedder:
        with self._lock:
            if self._embedder is None:
                from ai.embedding import BgeEmbedder

                self._embedder = BgeEmbedder()
            return self._embedder

    def reranker(self) -> Any:
        """Required for chat: the relevance policy is calibrated for BGE-small + MiniLM (contract RET-10)."""
        with self._lock:
            if self._reranker is None:
                from ai.retrieval.rerank import CrossEncoderReranker

                self._reranker = CrossEncoderReranker()
            return self._reranker

    def vector_store(self) -> VectorStore:
        with self._lock:
            if self._vector_store is None:
                from ai.vectorstore import ChromaVectorStore

                path = self.index_dir / "chroma"
                path.mkdir(parents=True, exist_ok=True, mode=0o700)
                self._vector_store = ChromaVectorStore(path=str(path))
            return self._vector_store

    def parent_store(self) -> ParentStore:
        with self._lock:
            if self._parent_store is None:
                from ai.storage import SQLiteParentStore

                self.index_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                self._parent_store = SQLiteParentStore(self.index_dir / "parents.sqlite3")
            return self._parent_store

    def retrieval(self) -> RetrievalService:
        embedder, reranker = self.embedder(), self.reranker()
        store, parents = self.vector_store(), self.parent_store()
        with self._lock:
            if self._retrieval is None:
                from ai.retrieval import RetrievalService

                self._retrieval = RetrievalService(embedder, store, parent_store=parents, reranker=reranker)
            return self._retrieval

    def close(self) -> None:
        if self._provider is not None:
            self._provider.close()
        if self._parent_store is not None and hasattr(self._parent_store, "close"):
            self._parent_store.close()

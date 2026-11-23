"""Optional second-stage reranking with a cross-encoder.

Bi-encoder search (BGE) is fast but scores a query and a passage independently; a cross-encoder reads them
together and is much better at telling a passage that *answers* from one that merely shares words.
The model is loaded lazily, only the top candidates are scored, and the service works without it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_MAX_PASSAGE_CHARS = 2500  # the model reads at most 512 tokens; longer text is cut, not rejected


class Reranker(Protocol):
    """Scores ``(query, passage)`` pairs; a higher score means more relevant. Scores are model-specific."""

    name: str

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str = DEFAULT_RERANKER_MODEL, *, batch_size: int = 16, device: str | None = None) -> None:
        self.name = model_name
        self._batch_size = batch_size
        self._device = device
        self._model: object | None = None

    def _load(self) -> object:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.name, max_length=512, device=self._device)
        return self._model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        model = self._load()
        pairs = [(query, passage[:_MAX_PASSAGE_CHARS]) for passage in passages]
        scores = model.predict(pairs, batch_size=self._batch_size, show_progress_bar=False)  # type: ignore[attr-defined]
        return [float(s) for s in scores]

"""Token counting. Chunk budgets are expressed in the embedding model's own tokens."""

from __future__ import annotations

import logging
import math
from typing import Protocol

from ai.chunking.config import EMBEDDING_MODEL

logger = logging.getLogger(__name__)


class TokenCounter(Protocol):
    """Anything that can count tokens and say what it is (recorded on each chunk)."""

    name: str

    def count(self, text: str) -> int: ...


class ApproxTokenCounter:
    """~4 characters per token. Deterministic, dependency-free fallback (and test default)."""

    name = "approx-char4"

    def count(self, text: str) -> int:
        return math.ceil(len(text) / 4) if text else 0


class HFTokenCounter:
    """Exact counts using the embedding model's tokenizer (downloads it on first use)."""

    def __init__(self, model_name: str = EMBEDDING_MODEL) -> None:
        from transformers import AutoTokenizer  # lazy: heavy import, optional dependency

        self._tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.name = f"hf:{model_name}"

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._tokenizer.encode(text, add_special_tokens=False, verbose=False))


def default_token_counter(model_name: str = EMBEDDING_MODEL) -> TokenCounter:
    """The model tokenizer when available, otherwise the approximate counter (logged)."""
    try:
        return HFTokenCounter(model_name)
    except Exception as exc:  # missing package, offline, ...
        logger.warning("Falling back to approximate token counting: %s", exc)
        return ApproxTokenCounter()

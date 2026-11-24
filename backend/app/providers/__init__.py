"""LLM provider abstraction. Every provider satisfies ``ai.answering.llm.LLMClient``, so ``AnswerService`` (and the
summary and quiz services later) work with any of them unchanged."""

from backend.app.providers.base import LLMProvider, ProviderCapabilities
from backend.app.providers.factory import build_provider
from backend.app.providers.openai_compatible import (
    DeepSeekProvider,
    FutureLocalProvider,
    LocalProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
)

__all__ = [
    "DeepSeekProvider",
    "FutureLocalProvider",
    "LLMProvider",
    "LocalProvider",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "ProviderCapabilities",
    "build_provider",
]

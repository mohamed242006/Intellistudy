"""The provider interface.

``LLMProvider`` extends the ``LLMClient`` protocol that ``ai/answering`` already uses (``model_name`` + ``generate``)
with a provider name and declared capabilities, so callers can adapt (e.g. not ask for JSON mode where unsupported)
and health/usage reporting can name the provider without exposing configuration (SEC-08).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ai.answering.models import LLMResponse, Message


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    #: the model accepts ``temperature`` (reasoning models may reject it or ignore it)
    temperature: bool = True
    #: request field that bounds the output: ``max_tokens`` or ``max_completion_tokens``
    max_tokens_field: str = "max_tokens"
    #: ``response_format: {"type": "json_object"}`` is supported
    json_mode: bool = False
    #: the provider can switch a model's thinking / reasoning mode off per request
    thinking_control: bool = False


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model_name: str
    capabilities: ProviderCapabilities

    def generate(
        self, messages: Sequence[Message], *, temperature: float = 0.0, max_tokens: int = 700
    ) -> LLMResponse: ...

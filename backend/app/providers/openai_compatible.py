"""Providers that speak the OpenAI-compatible ``POST {base_url}/chat/completions`` protocol.

Security (contract SEC-01, SEC-06, SEC-07):
    * the API key is read from settings (environment) and sent only in the ``Authorization`` header;
    * the base URL comes from configuration only, never from a request;
    * provider error bodies are logged with the key redacted and are never returned to clients; callers receive an
      ``LLMError`` with a generic message (``AnswerService`` turns it into an ``llm_unavailable`` refusal);
    * transient failures (408, 409, 429, 5xx, network errors) are retried with exponential backoff and jitter
      (NFR-REL-03); other errors are not retried.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from ai.answering.llm import LLMError
from ai.answering.models import LLMResponse, Message
from backend.app.core.logging import redact
from backend.app.providers.base import ProviderCapabilities

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})
_MAX_LOGGED_BODY = 500


class OpenAICompatibleProvider:
    """Generic client; subclasses fix the name, default endpoint, default model and capabilities."""

    name = "openai-compatible"
    default_base_url = ""
    default_model = ""
    capabilities = ProviderCapabilities()

    def __init__(
        self,
        *,
        api_key: SecretStr | None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
        backoff: float = 1.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.model_name = model or self.default_model
        base = (base_url or self.default_base_url).rstrip("/")
        if not base.startswith(("https://", "http://")):
            raise ValueError("provider base URL must be an absolute http(s) URL from configuration")
        self._url = f"{base}/chat/completions"
        self._api_key = api_key
        self._max_retries = max_retries
        self._backoff = backoff
        self._sleep = sleep
        self._extra = dict(extra_body or {})
        self._client = httpx.Client(timeout=timeout, transport=transport, follow_redirects=False)

    # --------------------------------------------------------------------------------------------- protocol
    def generate(
        self, messages: Sequence[Message], *, temperature: float = 0.0, max_tokens: int = 700
    ) -> LLMResponse:
        payload = self.build_payload(messages, temperature=temperature, max_tokens=max_tokens)
        headers = {"Content-Type": "application/json"}
        secret = self._api_key.get_secret_value() if self._api_key is not None else ""
        if secret:
            headers["Authorization"] = f"Bearer {secret}"

        for attempt in range(self._max_retries + 1):
            started = time.monotonic()
            retryable = True
            try:
                response = self._client.post(self._url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                logger.warning("%s: endpoint unreachable (%s), attempt %d", self.name, type(exc).__name__, attempt + 1)
                error = LLMError("model endpoint unreachable", retryable=True)
            else:
                if response.status_code == 200:
                    try:
                        return self.parse(response.json(), time.monotonic() - started)
                    except (ValueError, KeyError, IndexError, TypeError) as exc:
                        raise LLMError(f"malformed reply from the model endpoint ({type(exc).__name__})") from None
                retryable = response.status_code in RETRYABLE_STATUS
                logger.warning(
                    "%s: HTTP %d on attempt %d: %s", self.name, response.status_code, attempt + 1,
                    redact(response.text[:_MAX_LOGGED_BODY], [secret]),
                )
                error = LLMError(f"HTTP {response.status_code} from the model endpoint", retryable=retryable)
            if not retryable or attempt == self._max_retries:
                raise error
            self._sleep(self._backoff * (2**attempt) * (0.5 + random.random()))
        raise LLMError("model endpoint unavailable", retryable=True)  # unreachable; keeps type checkers happy

    # ------------------------------------------------------------------------------------- request / reply
    def build_payload(self, messages: Sequence[Message], *, temperature: float, max_tokens: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            self.capabilities.max_tokens_field: max_tokens,
        }
        if self.capabilities.temperature:
            payload["temperature"] = temperature
        payload.update(self._extra)
        return payload

    def parse(self, data: dict[str, Any], latency: float) -> LLMResponse:
        choice = data["choices"][0]
        text = (choice.get("message") or {}).get("content")
        if not isinstance(text, str):
            raise ValueError("no text in reply")
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=str(data.get("model") or self.model_name),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            finish_reason=str(choice.get("finish_reason") or ""),
            latency_s=latency,
        )

    def close(self) -> None:
        self._client.close()


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek's hosted API (current provider).

    ``deepseek-chat`` is the configuration validated on the 111-case benchmark (2026-11-23; served as
    ``deepseek-flash`` in non-thinking mode). DeepSeek's current model names think by default and ignore
    ``temperature`` while thinking, so for any model other than the legacy ``deepseek-chat`` the provider switches
    thinking off explicitly, keeping the validated conditions.
    """

    name = "deepseek"
    default_base_url = "https://api.deepseek.com"
    default_model = "deepseek-chat"
    capabilities = ProviderCapabilities(json_mode=True, thinking_control=True)
    LEGACY_NON_THINKING = frozenset({"deepseek-chat"})

    def build_payload(self, messages: Sequence[Message], *, temperature: float, max_tokens: int) -> dict[str, Any]:
        payload = super().build_payload(messages, temperature=temperature, max_tokens=max_tokens)
        if self.model_name not in self.LEGACY_NON_THINKING:
            payload.setdefault("thinking", {"type": "disabled"})
        return payload


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI's API. Newer models reject ``max_tokens`` and a fixed ``temperature``; the request adapts by model."""

    name = "openai"
    default_base_url = "https://api.openai.com/v1"
    default_model = "gpt-4.1-mini"
    #: model-name prefixes that take ``max_completion_tokens`` and no ``temperature``
    REASONING_PREFIXES = ("o1", "o3", "o4", "gpt-5", "gpt-6")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        reasoning = self.model_name.startswith(self.REASONING_PREFIXES)
        self.capabilities = ProviderCapabilities(
            temperature=not reasoning,
            max_tokens_field="max_completion_tokens" if reasoning else "max_tokens",
            json_mode=True,
        )


class LocalProvider(OpenAICompatibleProvider):
    """A self-hosted OpenAI-compatible server (Ollama, vLLM, LM Studio): the "future local" provider slot
    (e.g. Gemma 3 27B on a GPU). No API key; the URL comes from configuration."""

    name = "local"
    default_base_url = "http://localhost:11434/v1"
    default_model = "qwen2.5:3b-instruct"


#: Name used in the project plan (2026-11-24) for the self-hosted provider slot.
FutureLocalProvider = LocalProvider

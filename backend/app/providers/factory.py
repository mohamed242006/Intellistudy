"""Build the configured provider from settings (environment only, SEC-01)."""

from __future__ import annotations

from backend.app.core.config import LLMProviderName, Settings, is_placeholder
from backend.app.providers.openai_compatible import (
    DeepSeekProvider,
    LocalProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
)

_PROVIDERS: dict[LLMProviderName, type[OpenAICompatibleProvider]] = {
    LLMProviderName.DEEPSEEK: DeepSeekProvider,
    LLMProviderName.OPENAI: OpenAIProvider,
    LLMProviderName.LOCAL: LocalProvider,
}


def build_provider(settings: Settings) -> OpenAICompatibleProvider | None:
    """The configured provider, or ``None`` when no usable provider is configured.

    ``None`` is a normal state in the demo profile without a key: LLM features then answer ``llm_unavailable``
    (SEC-05). In ``prod`` a missing key already stopped startup in ``Settings``.
    """
    if settings.llm_provider is LLMProviderName.NONE:
        return None
    cls = _PROVIDERS[settings.llm_provider]
    key = settings.provider_api_key
    if cls is not LocalProvider and is_placeholder(key):
        return None
    return cls(
        api_key=None if cls is LocalProvider else key,
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )

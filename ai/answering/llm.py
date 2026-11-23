"""LLM adapter: one small interface, so OpenAI, a local Gemma/Qwen behind vLLM or Ollama, or a test double plug in alike.

``OpenAICompatibleClient`` speaks the de-facto standard ``/chat/completions`` JSON protocol with the standard
library only (no SDK dependency), retries transient failures with backoff, and never logs credentials.
``ExtractiveLLM`` is a deterministic no-model baseline: it answers by quoting the best-matching sentences of the
provided sources, with citations. It makes the whole answer layer testable and usable offline, and is the baseline a
real model has to beat. ``ScriptedLLM`` replays canned replies in tests.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from ai.answering.models import LLMResponse, Message
from ai.retrieval.assessment import content_terms

INSUFFICIENT = "INSUFFICIENT_CONTEXT"


class LLMError(Exception):
    """The model could not produce a reply. ``retryable`` is a hint for the caller's own retry policy."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMClient(Protocol):
    model_name: str

    def generate(
        self, messages: Sequence[Message], *, temperature: float = 0.0, max_tokens: int = 700
    ) -> LLMResponse: ...


class OpenAICompatibleClient:
    """``POST {base_url}/chat/completions`` - OpenAI, vLLM, Ollama (OpenAI mode), LM Studio, ..."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        timeout: float = 60.0,
        max_retries: int = 2,
        backoff: float = 1.0,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.model_name = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key if api_key is not None else os.environ.get(api_key_env, "")
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff = backoff
        self._extra = extra_body or {}

    def generate(
        self, messages: Sequence[Message], *, temperature: float = 0.0, max_tokens: int = 700
    ) -> LLMResponse:
        payload = {
            "model": self.model_name,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self._extra,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        last: LLMError | None = None
        for attempt in range(self._max_retries + 1):
            started = time.time()
            try:
                request = urllib.request.Request(self._url, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                return self._parse(data, time.time() - started)
            except urllib.error.HTTPError as exc:
                retryable = exc.code in (408, 409, 429) or exc.code >= 500
                last = LLMError(f"HTTP {exc.code} from the model endpoint", retryable=retryable)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last = LLMError(f"model endpoint unreachable: {type(exc).__name__}", retryable=True)
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"malformed reply from the model endpoint: {type(exc).__name__}") from exc
            if not last.retryable or attempt == self._max_retries:
                break
            time.sleep(self._backoff * (2**attempt))
        assert last is not None
        raise last

    def _parse(self, data: dict[str, Any], latency: float) -> LLMResponse:
        choice = data["choices"][0]
        usage = data.get("usage") or {}
        text = (choice.get("message") or {}).get("content")
        if not isinstance(text, str):
            raise ValueError("no text in reply")
        return LLMResponse(
            text=text,
            model=str(data.get("model") or self.model_name),
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            finish_reason=str(choice.get("finish_reason") or ""),
            latency_s=latency,
        )


class ScriptedLLM:
    """Replays replies in order (the last one repeats); a callable computes the reply from the messages.

    The reply ``"__error__"`` raises a retryable :class:`LLMError`.
    """

    def __init__(self, replies: Sequence[str] | Callable[[Sequence[Message]], str], model: str = "scripted") -> None:
        self.model_name = model
        self._replies = replies
        self.calls: list[list[Message]] = []

    def generate(
        self, messages: Sequence[Message], *, temperature: float = 0.0, max_tokens: int = 700
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if callable(self._replies):
            text = self._replies(messages)
        else:
            text = self._replies[min(len(self.calls) - 1, len(self._replies) - 1)]
        if text == "__error__":
            raise LLMError("scripted failure", retryable=True)
        return LLMResponse(
            text=text,
            model=self.model_name,
            prompt_tokens=sum(len(m.content) // 4 for m in messages),
            completion_tokens=len(text) // 4,
        )


_SOURCE = re.compile(r'<source id="(S\d+)"[^>]*>\n(.*?)\n</source>', re.DOTALL)
_QUESTION = re.compile(r"Question:\s*(.*)\Z", re.DOTALL)
_LEADERS = re.compile(r"(?:\s*\.){3,}")
_TOC_ENTRY = re.compile(r"^\d+(?:\.\d+)*\.?\s+.*\s\d{1,3}$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


class ExtractiveLLM:
    """No model: quote the sentences of the sources that best cover the question's words, citing each.

    A deterministic baseline and offline fallback. It cannot paraphrase or combine facts, but it cannot hallucinate
    either, which makes it a useful floor for a real model and a way to test the surrounding machinery.
    """

    model_name = "extractive-baseline"

    def __init__(self, max_sentences: int = 2, min_coverage: float = 0.5) -> None:
        self._max = max_sentences
        self._min = min_coverage

    def generate(
        self, messages: Sequence[Message], *, temperature: float = 0.0, max_tokens: int = 700
    ) -> LLMResponse:
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        found = _QUESTION.search(user)
        wanted = content_terms(found.group(1).strip() if found else "")
        scored: list[tuple[float, int, str, str]] = []
        for tag, body in _SOURCE.findall(user):
            for raw in _SENTENCE.split(_LEADERS.sub(" ", body)):
                sentence = raw.strip(" -*\t")
                letters = sum(ch.isalpha() for ch in sentence)
                if _TOC_ENTRY.match(sentence):
                    continue  # "7.3 Indexing Layer 11": a table-of-contents entry, not content
                if len(sentence.split()) < 4 or letters < 0.6 * len(sentence.replace(" ", "")):
                    continue  # too short, or mostly punctuation / digits (dot leaders, page numbers)
                have = set(content_terms(sentence))
                coverage = sum(1 for t in wanted if t in have) / len(wanted) if wanted else 0.0
                scored.append((coverage, -len(scored), tag, sentence))
        scored.sort(reverse=True)
        chosen = [s for s in scored if s[0] >= self._min][: self._max]
        if not chosen:
            return LLMResponse(text=INSUFFICIENT, model=self.model_name)
        text = " ".join(f"{sentence} [{tag}]" for _coverage, _order, tag, sentence in chosen)
        return LLMResponse(text=text, model=self.model_name)

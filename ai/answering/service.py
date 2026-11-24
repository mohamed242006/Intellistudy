"""Answer Service: retrieve -> decide -> build context -> prompt -> model -> validate -> cited answer or refusal.

    service = AnswerService(retrieval_service, llm_client)
    answer = service.answer("What is a join point?", user_id="u1", course_id="c1")
    answer.text, answer.citations, answer.refused

Guarantees (each covered by tests):
    * retrieval is always scoped to one user and course; nothing else is ever put in the prompt;
    * an answer is returned only if at least one sentence cites an offered source and passes the grounding check;
      anything else is a refusal with a stated reason - never an uncited or invented answer;
    * unrelated questions are refused before the model is called;
    * a model outage is a refusal (``llm_unavailable``), not an exception;
    * the prompt version, model name and token usage are recorded on every answer.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from typing import Protocol

from ai.answering import citations as citation_tools
from ai.answering.context import ContextBuilder
from ai.answering.grounding import GroundingPolicy, check
from ai.answering.llm import INSUFFICIENT, LLMClient, LLMError
from ai.answering.models import (
    LLM_UNAVAILABLE,
    MODEL_DECLINED,
    UNCITED,
    UNSUPPORTED,
    Answer,
    ContextBundle,
    GroundingReport,
)
from ai.answering.prompt import PROMPT_VERSION, build_messages
from ai.answering.refusal import RefusalPolicy, message, pre_check
from ai.chunking.interfaces import FilterValue
from ai.retrieval.models import RetrievalResult


class Retriever(Protocol):
    """What the answer service needs from retrieval: ``RetrievalService`` or any scoped view of it (e.g. the backend's
    ready-only ``BoundRetrieval``)."""

    def search(self, query: str, *, user_id: str, course_id: str, k: int = 5,
               document_uids: Sequence[str] | None = None,
               filters: Mapping[str, FilterValue] | None = None) -> RetrievalResult: ...

logger = logging.getLogger(__name__)


class AnswerService:
    def __init__(
        self,
        retrieval: Retriever,
        llm: LLMClient,
        *,
        context_builder: ContextBuilder | None = None,
        refusal: RefusalPolicy | None = None,
        grounding: GroundingPolicy | None = None,
        k: int = 6,
        max_attempts: int = 2,
        temperature: float = 0.0,
        max_tokens: int = 700,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.retrieval = retrieval
        self.llm = llm
        self.context_builder = context_builder or ContextBuilder()
        self.refusal = refusal or RefusalPolicy()
        self.grounding = grounding or GroundingPolicy()
        self.k = k
        self.max_attempts = max_attempts
        self.temperature = temperature
        self.max_tokens = max_tokens

    def answer(
        self,
        question: str,
        *,
        user_id: str,
        course_id: str,
        document_uids: Sequence[str] | None = None,
        filters: Mapping[str, FilterValue] | None = None,
    ) -> Answer:
        text = (question or "").strip()
        if not text:
            raise ValueError("question must not be empty")
        started = time.time()
        result = self.retrieval.search(
            text, user_id=user_id, course_id=course_id, k=self.k, document_uids=document_uids, filters=filters
        )
        answer = Answer(
            question=text,
            text="",
            assessment=result.assessment,
            model=self.llm.model_name,
            prompt_version=PROMPT_VERSION,
            warnings=list(result.warnings),
        )
        bundle = self.context_builder.build(text, result)
        answer.warnings.extend(bundle.warnings)
        decision = pre_check(result, self.refusal)
        if decision.warning:
            answer.warnings.append(decision.warning)
        if decision.refuse:
            return self._refuse(answer, decision.reason, bundle, started)

        answer.sources = list(bundle.sources)
        answer.confidence = result.assessment.level if result.assessment is not None else ""
        problem = ""
        for attempt in range(self.max_attempts):
            last = attempt + 1 == self.max_attempts
            try:
                reply = self.llm.generate(
                    build_messages(bundle, caution=decision.caution, repair=problem),
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
            except LLMError as exc:
                logger.warning("model call failed: %s", exc)
                answer.warnings.append(f"model error: {exc}")
                return self._refuse(answer, LLM_UNAVAILABLE, bundle, started)
            answer.llm_calls += 1
            answer.prompt_tokens += reply.prompt_tokens
            answer.completion_tokens += reply.completion_tokens
            answer.model = reply.model or answer.model

            reply_text = reply.text.strip()
            if reply_text.upper().startswith(INSUFFICIENT):
                return self._refuse(answer, MODEL_DECLINED, bundle, started)

            parsed = citation_tools.parse(reply_text, bundle)
            if parsed.invalid_tags:
                answer.warnings.append(f"model cited sources that were not provided: {', '.join(parsed.invalid_tags)}")
            if not any(s.tags for s in parsed.sentences):
                problem = "it did not cite any of the provided sources"
                if last:
                    return self._refuse(answer, UNCITED, bundle, started)
                continue

            kept, report = check(parsed.sentences, bundle, self.grounding)
            if not any(s.tags for s in kept):
                problem = "none of its claims was supported by the cited sources"
                answer.grounding = report
                if last:
                    return self._refuse(answer, UNSUPPORTED, bundle, started)
                continue

            final_text, cited = citation_tools.render(kept, bundle)
            answer.text = final_text
            answer.citations = cited
            answer.grounding = report
            answer.contains_generated_text = any(c.source.generated for c in cited)
            for removed_text, reason in report.removed:
                answer.warnings.append(f"removed an unsupported sentence ({reason}): {removed_text[:80]}")
            if answer.contains_generated_text:
                answer.warnings.append("the answer relies on AI-generated figure text")
            answer.seconds = time.time() - started
            return answer
        return self._refuse(answer, UNCITED, bundle, started)  # unreachable with max_attempts >= 1; defensive

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _refuse(answer: Answer, reason: str, bundle: ContextBundle, started: float) -> Answer:
        nearest = list(bundle.sources[:3])
        missing = answer.assessment.missing_terms if answer.assessment is not None else ()
        answer.refused = True
        answer.refusal_reason = reason
        answer.nearest = nearest
        answer.text = message(reason, missing_terms=missing, nearest=nearest[0] if nearest else None)
        answer.citations = []
        if answer.grounding is None:
            answer.grounding = GroundingReport()
        answer.seconds = time.time() - started
        return answer


__all__ = ["UNCITED", "UNSUPPORTED", "AnswerService"]

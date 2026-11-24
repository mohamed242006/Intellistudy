"""Grounded chat (M3; docs/M3_RELEASE_GATE.md).

A question goes through, in order: conversation ownership (OWN-03) -> chat rate limit (9a) -> daily token budget
(UPL-16, read from the usage ledger; every provider call is recorded there, F-M3-05) -> READY-only scope (``ScopedRetrieval``, release blocker F-M2-10) -> the unchanged ``AnswerService`` over a
``BoundRetrieval`` and the configured provider -> **citation ownership validation** (every citation from the
caller's ready documents in this course, passage equal to the retrieved chunk; COW-02/04) -> chat state -> stored
message with its citations (FR-CIT-05).

Provider failures never raise out of here: ``AnswerService`` turns ``LLMError`` into the ``llm_unavailable`` refusal,
and :class:`_SafeLLM` turns any other provider exception into an ``LLMError`` first (PRV-01..07).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai.answering import AnswerService
from ai.answering.llm import LLMError
from ai.answering.models import Answer, LLMResponse, SourceRef
from ai.answering.models import Message as LLMMessage
from backend.app.core.clock import Clock
from backend.app.core.config import Settings
from backend.app.core.errors import ApiError
from backend.app.core.logging import security_event
from backend.app.core.ratelimit import LIMITS, RateLimiter, enforce
from backend.app.db.models import ChatState, Conversation, Message, UsageFeature, User
from backend.app.services.ai_container import AIContainer
from backend.app.services.ownership import get_owned
from backend.app.services.retrieval import ScopedRetrieval, ready_document_ids
from backend.app.services.usage import MeteredLLM, UsageLedger

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 2000
SCOPE_VIOLATION = "scope_violation"
_INVALID_TAG_WARNING = "model cited sources that were not provided"

NOTICES = {
    "no_results": "Nothing in your ready documents for this course matches the question.",
    "not_relevant": "Your materials don't cover this question, so no answer was generated.",
    "model_declined": "The sources don't contain enough information to answer this.",
    "uncited_answer": "An answer could not be backed by your materials, so it was withheld.",
    "unsupported_claims": "The draft answer was not supported by your materials, so it was withheld.",
    "llm_unavailable": "The answering service is unavailable right now. Try again later.",
    SCOPE_VIOLATION: "The answer was withheld because it referenced material outside this course.",
    ChatState.PARTIAL.value: "Only part of your question is covered by your materials.",
    ChatState.LOW_CONFIDENCE.value: "Check the cited passages before relying on this answer.",
}


def normalize_question(raw: str) -> str:
    """NFC, control characters removed (tab/newline become spaces), whitespace collapsed (G3-PI-07)."""
    text = unicodedata.normalize("NFC", raw)
    text = "".join(" " if ch in "\t\r\n" else ch for ch in text if ch in "\t\r\n" or unicodedata.category(ch) not in
                   {"Cc", "Cf", "Cs", "Co", "Cn"})
    return re.sub(r"\s+", " ", text).strip()


_MARKDOWN_IMAGE = re.compile(r"!\[([^\]\n]{0,200})\]\([^)\n]*\)")
_HTML_IMAGE = re.compile(r"<\s*img\b[^>]*>", re.IGNORECASE)


def sanitize_answer_text(text: str) -> str:
    """Remove constructs a renderer would fetch automatically (finding F-M3-02): markdown and HTML images become
    their alt text, so an injected document cannot make the client load ``https://attacker/?data=...``."""
    text = _MARKDOWN_IMAGE.sub(lambda m: m.group(1), text)
    return _HTML_IMAGE.sub("", text)


def chat_state(answer: Answer) -> ChatState:
    """The confirmed precedence: refused > partial > low_confidence > answered."""
    if answer.refused:
        return ChatState.REFUSED
    if answer.assessment is not None and answer.assessment.missing_terms:
        return ChatState.PARTIAL
    low = (
        (answer.assessment is not None and answer.assessment.level == "weak")
        or any(c.source.low_confidence for c in answer.citations)
        or answer.contains_generated_text
        or bool(answer.grounding is not None and answer.grounding.removed)
        or any(w.startswith(_INVALID_TAG_WARNING) for w in answer.warnings)
    )
    return ChatState.LOW_CONFIDENCE if low else ChatState.ANSWERED


class _UnavailableLLM:
    """Stands in when no provider is configured (demo without a key): every call is ``llm_unavailable``."""

    model_name = "unavailable"

    def generate(self, messages: Sequence[LLMMessage], *, temperature: float = 0.0, max_tokens: int = 700
                 ) -> LLMResponse:
        raise LLMError("no model provider is configured")


class _SafeLLM:
    """Any non-``LLMError`` provider exception becomes an ``LLMError`` (logged by type only), so a provider fault is a
    refusal, never a 500 (PRV-01..07)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.model_name = str(getattr(inner, "model_name", "unknown"))

    def generate(self, messages: Sequence[LLMMessage], *, temperature: float = 0.0, max_tokens: int = 700
                 ) -> LLMResponse:
        try:
            reply: LLMResponse = self._inner.generate(messages, temperature=temperature, max_tokens=max_tokens)
        except LLMError:
            raise
        except Exception as exc:
            logger.warning("provider raised %s", type(exc).__name__)
            raise LLMError("model call failed") from None
        if not isinstance(getattr(reply, "text", None), str):
            raise LLMError("malformed reply from the model endpoint")
        return reply


class ChatService:
    def __init__(self, settings: Settings, ai: AIContainer, limiter: RateLimiter, clock: Clock,
                 ledger: UsageLedger | None = None) -> None:
        self._settings = settings
        self._ledger = ledger or UsageLedger(settings, clock)
        self._ai = ai
        self._limiter = limiter
        self._clock = clock
        self._scoped = ScopedRetrieval(ai)

    # ------------------------------------------------------------------------------------ conversations
    def create_conversation(self, session: Session, user: User, course_id: str, title: str | None) -> Conversation:
        course, _ = self._scoped.resolve_scope(session, user, course_id)
        conversation = Conversation(owner_id=user.id, course_id=course.id,
                                    title=(title or "New conversation").strip()[:200] or "New conversation")
        session.add(conversation)
        session.commit()
        return conversation

    def list_conversations(self, session: Session, user: User, course_id: str, *, limit: int, offset: int
                           ) -> list[Conversation]:
        course, _ = self._scoped.resolve_scope(session, user, course_id)
        return list(session.scalars(
            select(Conversation).where(Conversation.owner_id == user.id, Conversation.course_id == course.id)
            .order_by(Conversation.updated_at.desc(), Conversation.id).limit(limit).offset(offset)))

    def get_conversation(self, session: Session, user: User, conversation_id: str) -> tuple[Conversation, list[Message]]:
        conversation = get_owned(session, Conversation, conversation_id, user.id, resource="conversation")
        messages = list(session.scalars(
            select(Message).where(Message.conversation_id == conversation.id, Message.owner_id == user.id)
            .order_by(Message.created_at, Message.id)))
        return conversation, messages

    def delete_conversation(self, session: Session, user: User, conversation_id: str) -> None:
        conversation = get_owned(session, Conversation, conversation_id, user.id, resource="conversation")
        session.delete(conversation)
        session.commit()

    # ------------------------------------------------------------------------------------------- asking
    def ask(self, session: Session, user: User, conversation_id: str, question: str,
            document_ids: Sequence[str] | None) -> Message:
        conversation = get_owned(session, Conversation, conversation_id, user.id, resource="conversation")
        text = normalize_question(question)
        if not text or len(text) > MAX_QUESTION_CHARS:
            raise ApiError(422, f"Ask a question of 1-{MAX_QUESTION_CHARS} characters.", code="invalid_question")
        enforce(self._limiter, LIMITS["chat:user"], user.id, actor=user.id)
        self._ledger.check(session, user.id)
        course, scope = self._scoped.resolve_scope(session, user, conversation.course_id, document_ids)

        bound = self._scoped.bind(session, user, course, scope)
        provider = self._ai.provider
        llm = (MeteredLLM(_SafeLLM(provider), self._ledger, session, user.id, UsageFeature.CHAT)
               if provider is not None else _UnavailableLLM())
        service = AnswerService(bound, llm, k=self._settings.chat_retrieval_k,
                                max_tokens=self._settings.chat_max_tokens)
        answer = service.answer(text, user_id=user.id, course_id=course.id)

        answer = self._validate_citations(session, user, course.id, scope, bound, answer)
        answer.text = sanitize_answer_text(answer.text)
        state = chat_state(answer)
        message = Message(
            conversation_id=conversation.id, owner_id=user.id, question=text, state=state.value,
            text=answer.text, citations=[_citation(c.number, c.source) for c in answer.citations],
            refusal_reason=answer.refusal_reason or None, notice=self._notice(state, answer),
            missing_terms=list(answer.assessment.missing_terms) if answer.assessment else [],
            nearest=[_source(s) for s in answer.nearest], warnings=[w[:300] for w in answer.warnings][:20],
            model=(answer.model or llm.model_name)[:100], prompt_tokens=answer.prompt_tokens,
            completion_tokens=answer.completion_tokens, seconds=round(answer.seconds, 3),
            created_at=self._clock.now(), updated_at=self._clock.now(),
        )
        session.add(message)
        conversation.updated_at = self._clock.now()
        session.commit()
        return message

    # ------------------------------------------------------------------------------- citation ownership
    def _validate_citations(self, session: Session, user: User, course_id: str, scope: frozenset[str],
                            bound: Any, answer: Answer) -> Answer:
        """COW-02/04: every cited (and offered) source is a retrieved chunk of the caller's ready document in this
        course, quoted verbatim. Any violation withholds the whole answer and is logged."""
        if answer.refused:
            return answer
        retrieved: dict[str, str] = {}
        result = bound.last.result if bound.last is not None else None
        if result is not None:
            retrieved = {h.chunk_id: h.text for h in result.hits}
        cited_docs = {c.source.document_uid for c in answer.citations}
        ready = ready_document_ids(session, user.id, course_id, within=cited_docs) if cited_docs else set()
        problems = []
        for citation in answer.citations:
            source = citation.source
            if source.document_uid not in scope or source.document_uid not in ready:
                problems.append("document_outside_scope")
            elif retrieved.get(source.chunk_id) != source.text:
                problems.append("passage_not_retrieved")
        if not problems:
            return answer
        security_event("citation_scope_violation", user_id=user.id, course_id=course_id, problems=sorted(set(problems)))
        answer.refused = True
        answer.refusal_reason = SCOPE_VIOLATION
        answer.text = NOTICES[SCOPE_VIOLATION]
        answer.citations = []
        answer.nearest = []
        return answer

    # ------------------------------------------------------------------------------------------ helpers
    def _notice(self, state: ChatState, answer: Answer) -> str | None:
        if state is ChatState.REFUSED:
            return NOTICES.get(answer.refusal_reason, NOTICES["no_results"])
        if state is ChatState.PARTIAL:
            missing = ", ".join(answer.assessment.missing_terms[:5]) if answer.assessment else ""
            return f"{NOTICES[state.value]} Not found: {missing}." if missing else NOTICES[state.value]
        if state is ChatState.LOW_CONFIDENCE:
            return NOTICES[state.value]
        return None



def _source(source: SourceRef) -> dict[str, object]:
    return {
        "document_id": source.document_uid, "file_name": source.file_name, "citation_label": source.citation_label,
        "page": source.page_number if source.slide_number is None else None, "slide": source.slide_number,
        "passage": source.text,
    }


def _citation(number: int, source: SourceRef) -> dict[str, object]:
    return {"number": number, **_source(source), "context": source.context,
            "low_confidence": source.low_confidence, "generated": source.generated}

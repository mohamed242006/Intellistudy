"""Shared fixture for M3 tests: M2's users, courses and real processing, plus a deterministic reranker that carries
the calibrated reranker's name (so the relevance policy stays active, as in production, contract RET-10)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from ai.retrieval.rerank import DEFAULT_RERANKER_MODEL
from backend.app.services.ai_container import AIContainer
from backend.app.services.retrieval import ScopedRetrieval
from backend.tests.m2_base import M2Case


class OverlapReranker:
    """Scores a passage by the share of query words it contains (deterministic, no model)."""

    name = DEFAULT_RERANKER_MODEL

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        words = set(re.findall(r"[a-z]{3,}", query.lower()))
        out = []
        for passage in passages:
            present = set(re.findall(r"[a-z]{3,}", passage.lower()))
            out.append(10.0 * len(words & present) / max(len(words), 1) - 2.0)
        return out


class M3Case(M2Case):
    def make_ai(self) -> AIContainer:
        container = super().make_ai()
        container._reranker = OverlapReranker()
        return container

    @property
    def scoped(self) -> ScopedRetrieval:
        return ScopedRetrieval(self.app.state.ai)

    def search(self, user_token_owner: str, course_id: str, query: str, document_ids: Any = None) -> Any:
        """Run a scoped search as ``user_token_owner`` (a user id) through the only allowed path."""
        from sqlalchemy import select

        from backend.app.db.models import User

        with self.db() as session:
            user = session.scalars(select(User).where(User.id == user_token_owner)).one()
            course, scope = self.scoped.resolve_scope(session, user, course_id, document_ids)
            return self.scoped.search(session, user, course, scope, query, k=6)


class ChatCase(M3Case):
    """M3 chat helpers: conversations, questions, and a scripted model in place of DeepSeek."""

    def set_model(self, replies: Any) -> Any:
        from ai.answering.llm import ScriptedLLM

        llm = ScriptedLLM(replies) if not hasattr(replies, "generate") else replies
        self.app.state.ai._provider = llm
        return llm

    def doc(self, client: Any, token: str, course_id: str, name: str, text: str) -> str:
        from backend.tests import m2_fixtures as fx

        document_id = str(self.upload_ok(client, token, course_id, (name, fx.pdf_bytes(text=text)))[0]["id"])
        self.process()
        return document_id

    def conversation(self, client: Any, token: str, course_id: str) -> str:
        response = client.post(f"/api/v1/courses/{course_id}/conversations", json={"title": "Study"},
                               headers=self.bearer(token))
        self.assertEqual(response.status_code, 201, response.text)
        return str(response.json()["id"])

    def ask(self, client: Any, token: str, conversation_id: str, question: str, **extra: Any) -> Any:
        return client.post(f"/api/v1/conversations/{conversation_id}/messages",
                           json={"question": question, **extra}, headers=self.bearer(token))

    def ask_ok(self, client: Any, token: str, conversation_id: str, question: str, **extra: Any) -> dict[str, Any]:
        response = self.ask(client, token, conversation_id, question, **extra)
        self.assertEqual(response.status_code, 201, response.text)
        return dict(response.json())

    @staticmethod
    def prompts(llm: Any) -> str:
        return "\n".join(m.content for call in llm.calls for m in call)


ZEBRA = "Zebra stripes confuse predators in the savanna grasslands. " * 6
QUOKKA = "Quokka marsupials smile on Rottnest island near Perth. " * 6

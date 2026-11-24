"""M3 release gate 2.2 cross-user retrieval isolation (G3-XUR-*) and 2.8 retrieval scope validation (G3-SCP-*)."""

from __future__ import annotations

import dataclasses
from typing import Any

from sqlalchemy import select

from ai.answering.llm import ExtractiveLLM
from ai.chunking.interfaces import ScoredRecord
from backend.app.db.models import Conversation, Message
from backend.tests import m2_fixtures as fx
from backend.tests.m3_base import QUOKKA, ZEBRA, ChatCase

QUOKKA_Q = "Why do quokka marsupials smile on Rottnest island?"
ZEBRA_Q = "Why do zebra stripes confuse predators?"


class CrossUserRetrievalTests(ChatCase):
    def setUp(self) -> None:
        super().setUp()
        self.set_model(ExtractiveLLM())
        self.a_doc = self.doc(self.a, self.a_token, self.a_course, "quokka.pdf", QUOKKA)
        self.b_doc = self.doc(self.b, self.b_token, self.b_course, "zebra.pdf", ZEBRA)
        self.a_conv = self.conversation(self.a, self.a_token, self.a_course)
        self.b_conv = self.conversation(self.b, self.b_token, self.b_course)

    def test_g3_xur_01_b_never_gets_a_answers_from_a_documents(self) -> None:
        llm = self.set_model(ExtractiveLLM())
        spy = self.set_model(_Recording(llm))
        message = self.ask_ok(self.b, self.b_token, self.b_conv, QUOKKA_Q)
        self.assertNotIn(self.a_doc, {c["document_id"] for c in message["citations"]})
        self.assertNotIn(self.a_doc, {s["document_id"] for s in message["nearest"]})
        self.assertNotIn("Quokka marsupials", message["text"])
        self.assertNotIn("Quokka marsupials smile", spy.prompt_text())

    def test_g3_xur_02_identical_bytes_cite_only_their_owner_copy(self) -> None:
        shared = "Mitochondria produce ATP through oxidative phosphorylation in cells. " * 6
        a_shared = self.doc(self.a, self.a_token, self.a_course, "bio.pdf", shared)
        b_shared = self.doc(self.b, self.b_token, self.b_course, "bio.pdf", shared)
        a_msg = self.ask_ok(self.a, self.a_token, self.a_conv, "How do mitochondria produce ATP?")
        b_msg = self.ask_ok(self.b, self.b_token, self.b_conv, "How do mitochondria produce ATP?")
        self.assertTrue(a_msg["citations"] and b_msg["citations"])
        self.assertEqual({c["document_id"] for c in a_msg["citations"]}, {a_shared})
        self.assertEqual({c["document_id"] for c in b_msg["citations"]}, {b_shared})

    def test_g3_xur_03_b_cannot_use_a_course_or_conversation(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING"):
            created = self.b.post(f"/api/v1/courses/{self.a_course}/conversations", json={}, headers=self.bearer(self.b_token))
            posted = self.ask(self.b, self.b_token, self.a_conv, QUOKKA_Q)
        self.assert_same_404(created, self.b_token)
        self.assert_same_404(posted, self.b_token)
        with self.db() as session:
            self.assertEqual(session.scalars(select(Message).where(Message.conversation_id == self.a_conv)).all(), [])
            self.assertEqual(len(session.scalars(select(Conversation).where(Conversation.course_id == self.a_course)).all()), 1)

    def test_g3_xur_04_b_cannot_list_read_or_delete_a_conversations(self) -> None:
        self.ask_ok(self.a, self.a_token, self.a_conv, QUOKKA_Q)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            listed = self.b.get(f"/api/v1/courses/{self.a_course}/conversations", headers=self.bearer(self.b_token))
            read = self.b.get(f"/api/v1/conversations/{self.a_conv}", headers=self.bearer(self.b_token))
            deleted = self.b.delete(f"/api/v1/conversations/{self.a_conv}", headers=self.bearer(self.b_token))
        for response in (listed, read, deleted):
            self.assert_same_404(response, self.b_token)
        own = self.a.get(f"/api/v1/conversations/{self.a_conv}", headers=self.bearer(self.a_token)).json()
        self.assertEqual(len(own["messages"]), 1)
        b_list = self.b.get(f"/api/v1/courses/{self.b_course}/conversations", headers=self.bearer(self.b_token)).json()
        self.assertEqual([c["id"] for c in b_list["items"]], [self.b_conv])

    def test_g3_xur_05_foreign_records_from_the_store_are_dropped(self) -> None:
        original = self.vectors.query
        a_records = original(self._collection(), self.app.state.ai.embedder().embed_query(QUOKKA_Q),
                             user_id=self.a_id, course_id=self.a_course, k=3)
        self.assertTrue(a_records)

        def leaky(*args: Any, **kwargs: Any) -> Any:  # a faulty store returning A's records to B
            return list(original(*args, **kwargs)) + list(a_records)

        self.vectors.query = leaky  # type: ignore[method-assign]
        spy = self.set_model(_Recording(ExtractiveLLM()))
        try:
            with self.assertLogs("intellistudy.security", level="WARNING") as logs:
                message = self.ask_ok(self.b, self.b_token, self.b_conv, QUOKKA_Q)
        finally:
            self.vectors.query = original  # type: ignore[method-assign]
        self.assertIn("retrieval_scope_violation", [getattr(r, "security_event", {}).get("event") for r in logs.records])
        self.assertNotIn(self.a_doc, {c["document_id"] for c in message["citations"]} | {s["document_id"] for s in message["nearest"]})
        self.assertNotIn("Quokka marsupials smile", spy.prompt_text())

    def test_g3_xur_06_foreign_parent_context_is_never_attached(self) -> None:
        a_parent_key = sorted(self.parent_keys(self.a_doc))[0]
        original = self.vectors.query

        def pointing_at_a_parent(*args: Any, **kwargs: Any) -> Any:
            records = list(original(*args, **kwargs))
            hijacked = []
            for record in records:
                meta = dict(record.metadata)
                meta["parent_chunk_id"] = a_parent_key.split(":", 1)[1]
                meta["document_uid"] = self.a_doc  # claims A's document
                hijacked.append(ScoredRecord(id=record.id, document=record.document, metadata=meta, score=record.score))
            return hijacked

        self.vectors.query = pointing_at_a_parent  # type: ignore[method-assign]
        spy = self.set_model(_Recording(ExtractiveLLM()))
        try:
            with self.assertLogs("intellistudy.security", level="WARNING"):
                message = self.ask_ok(self.b, self.b_token, self.b_conv, ZEBRA_Q)
        finally:
            self.vectors.query = original  # type: ignore[method-assign]
        self.assertNotIn("Quokka marsupials smile", spy.prompt_text())
        self.assertNotIn(self.a_doc, {c["document_id"] for c in message["citations"]})
        self.assertEqual(self.parents.get_many([a_parent_key], user_id=self.b_id, course_id=self.b_course), {})

    def test_g3_xur_07_admin_cannot_read_a_conversation(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING"):
            response = self.c.get(f"/api/v1/conversations/{self.a_conv}", headers=self.bearer(self.c_token))
        self.assert_same_404(response, self.c_token)

    def _collection(self) -> str:
        from ai.chunking.config import collection_name

        return collection_name(self.app.state.ai.embedder().model_name)


class ScopeValidationTests(ChatCase):
    def setUp(self) -> None:
        super().setUp()
        self.set_model(ExtractiveLLM())
        self.zebra = self.doc(self.a, self.a_token, self.a_course, "zebra.pdf", ZEBRA)
        self.quokka = self.doc(self.a, self.a_token, self.a_course, "quokka.pdf", QUOKKA)
        self.conv = self.conversation(self.a, self.a_token, self.a_course)

    def test_g3_scp_01_store_is_queried_with_the_authenticated_scope(self) -> None:
        calls: list[dict[str, Any]] = []
        original = self.vectors.query

        def spy(collection: str, vector: Any, **kwargs: Any) -> Any:
            calls.append(kwargs)
            return original(collection, vector, **kwargs)

        self.vectors.query = spy  # type: ignore[method-assign]
        try:
            self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)
        finally:
            self.vectors.query = original  # type: ignore[method-assign]
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual((call["user_id"], call["course_id"]), (self.a_id, self.a_course))
            self.assertEqual(set(call["filters"]["document_uid"]), {self.zebra, self.quokka})

    def test_g3_scp_02_client_document_selection_is_validated(self) -> None:
        b_doc = self.doc(self.b, self.b_token, self.b_course, "b.pdf", "Bob private notes about volcano lava. " * 6)
        pending = self.upload_ok(self.a, self.a_token, self.a_course, ("p.pdf", fx.pdf_bytes(text="pending " * 40)))[0]["id"]
        for bad in (b_doc, pending, "not-a-uuid"):
            with self.subTest(document=bad[:12]), self.assertLogs("intellistudy.security", level="WARNING"):
                self.assert_same_404(self.ask(self.a, self.a_token, self.conv, ZEBRA_Q, document_ids=[bad]), self.a_token)
        message = self.ask_ok(self.a, self.a_token, self.conv, QUOKKA_Q, document_ids=[self.zebra])
        self.assertTrue({c["document_id"] for c in message["citations"]} | {s["document_id"] for s in message["nearest"]}
                        <= {self.zebra})

    def test_g3_scp_03_scope_fields_in_the_body_are_rejected(self) -> None:
        for field, value in (("user_id", self.b_id), ("course_id", self.b_course), ("filters", {"kind": "table"}),
                             ("owner_id", self.b_id)):
            with self.subTest(field=field):
                response = self.ask(self.a, self.a_token, self.conv, ZEBRA_Q, **{field: value})
                self.assertEqual(response.status_code, 422)
                self.assertIn("extra_forbidden", {e["type"] for e in response.json()["errors"]})

    def test_g3_scp_04_documents_of_another_course_are_rejected(self) -> None:
        other_course = self.create_course(self.a_token, "Other course")
        other_doc = self.doc(self.a, self.a_token, other_course, "o.pdf", "Volcano lava flows downhill quickly. " * 6)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            response = self.ask(self.a, self.a_token, self.conv, ZEBRA_Q, document_ids=[other_doc])
        self.assert_same_404(response, self.a_token)

    def test_g3_scp_05_reranker_and_relevance_policy_are_active(self) -> None:
        retrieval = self.app.state.ai.retrieval()
        self.assertIsNotNone(retrieval.reranker)
        self.assertEqual(retrieval.reranker.name, retrieval.policy.reranker_model)
        scoped = self.search(self.a_id, self.a_course, ZEBRA_Q)
        self.assertIsNotNone(scoped.result.assessment)
        self.assertTrue(all(h.rerank_score is not None for h in scoped.result.hits))

    def test_g3_scp_06_course_deletion_removes_its_conversations(self) -> None:
        self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.assertEqual(self.a.delete(f"/api/v1/courses/{self.a_course}", headers=self.bearer(self.a_token)).status_code, 204)
        with self.db() as session:
            self.assertEqual(session.scalars(select(Conversation).where(Conversation.id == self.conv)).all(), [])
            self.assertEqual(session.scalars(select(Message).where(Message.conversation_id == self.conv)).all(), [])
        self.assert_same_404(self.a.get(f"/api/v1/conversations/{self.conv}", headers=self.bearer(self.a_token)), self.a_token)


class _Recording:
    """Wraps a model and records the prompts it receives."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.model_name = getattr(inner, "model_name", "recording")
        self.calls: list[Any] = []

    def generate(self, messages: Any, **kwargs: Any) -> Any:
        self.calls.append(list(messages))
        return self.inner.generate(messages, **kwargs)

    def prompt_text(self) -> str:
        return "\n".join(m.content for call in self.calls for m in call)


_ = dataclasses  # kept for parity with other gate modules


if __name__ == "__main__":
    import unittest

    unittest.main()

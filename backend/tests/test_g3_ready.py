"""M3 release gate 2.1: READY-only retrieval (release blocker F-M2-10). docs/M3_RELEASE_GATE.md, G3-RDY-01..07.

Every test first proves that the non-ready document's vectors and parents **are in the stores**, so an empty result
shows the scope filter at work, not missing data.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from ai.answering import AnswerService
from ai.answering.llm import ScriptedLLM
from backend.app.db.models import Document, DocumentStatus, User
from backend.app.services.retrieval import NO_READY_DOCUMENTS, RETRIEVABLE_STATUSES
from backend.tests import m2_fixtures as fx
from backend.tests.m3_base import M3Case

ROOT = Path(__file__).resolve().parents[2]
READY_TEXT = "Zebra stripes confuse predators in the savanna grasslands. " * 6
HIDDEN_TEXT = "Quokka marsupials smile on Rottnest island near Perth. " * 6
HIDDEN_QUERY = "Why do quokka marsupials smile on Rottnest island?"
NON_READY = [s.value for s in DocumentStatus if s is not DocumentStatus.READY]


class ReadyOnlyCase(M3Case):
    def setUp(self) -> None:
        super().setUp()
        self.ready_doc = self.upload_ok(self.a, self.a_token, self.a_course, ("zebra.pdf", fx.pdf_bytes(text=READY_TEXT)))[0]["id"]
        self.hidden_doc = self.upload_ok(self.a, self.a_token, self.a_course,
                                         ("quokka.pdf", fx.pdf_bytes(text=HIDDEN_TEXT)))[0]["id"]
        self.process()
        self.assertTrue(self.vector_records(self.hidden_doc), "precondition: hidden document is indexed")
        self.assertTrue(self.parent_keys(self.hidden_doc))

    def set_status(self, document_id: str, status: str) -> None:
        with self.db() as session:
            session.execute(update(Document).where(Document.id == document_id).values(status=status))
            session.commit()

    def assert_hidden_absent(self, scoped: Any) -> None:
        result = scoped.result
        self.assertNotIn(self.hidden_doc, {h.document_uid for h in result.hits})
        self.assertNotIn(self.hidden_doc, {p.parent.document_uid for p in result.parents})
        self.assertNotIn(self.hidden_doc, scoped.scope)
        for hit in result.hits:
            self.assertNotIn("quokka", hit.text.lower())


class ReadyOnlyRetrievalTests(ReadyOnlyCase):
    def test_g3_rdy_01_every_non_ready_status_is_excluded(self) -> None:
        self.assertEqual(RETRIEVABLE_STATUSES, frozenset({"ready"}))
        baseline = self.search(self.a_id, self.a_course, HIDDEN_QUERY)
        self.assertIn(self.hidden_doc, {h.document_uid for h in baseline.result.hits})  # found while ready
        for status in NON_READY:
            with self.subTest(status=status):
                self.set_status(self.hidden_doc, status)
                self.assertTrue(self.vector_records(self.hidden_doc))  # still indexed
                scoped = self.search(self.a_id, self.a_course, HIDDEN_QUERY)
                self.assert_hidden_absent(scoped)
                self.assertEqual({h.document_uid for h in scoped.result.hits}, {self.ready_doc})
        self.assertEqual(len(NON_READY), 8)

    def test_g3_rdy_02_unknown_status_values_are_excluded(self) -> None:
        for raw in ("indexed", "processing", "READY", "ready ", " ready", "", "Ready"):
            with self.subTest(status=repr(raw)):
                self.set_status(self.hidden_doc, raw)
                self.assert_hidden_absent(self.search(self.a_id, self.a_course, HIDDEN_QUERY))

    def test_g3_rdy_04_document_leaving_ready_during_the_search_is_dropped(self) -> None:
        store = self.vectors
        original_query = store.query

        def query_then_delete(*args: Any, **kwargs: Any) -> Any:
            records = original_query(*args, **kwargs)
            self.set_status(self.hidden_doc, DocumentStatus.DELETING.value)  # flips after the scope was read
            return records

        store.query = query_then_delete  # type: ignore[method-assign]
        try:
            scoped = self.search(self.a_id, self.a_course, HIDDEN_QUERY)
        finally:
            store.query = original_query  # type: ignore[method-assign]
        self.assertIn(self.hidden_doc, scoped.scope)  # it was ready when the search started
        result = scoped.result
        self.assertNotIn(self.hidden_doc, {h.document_uid for h in result.hits})
        self.assertNotIn(self.hidden_doc, {p.parent.document_uid for p in result.parents})
        self.assertGreater(scoped.dropped_not_ready, 0)

    def test_g3_rdy_06_answer_never_uses_a_non_ready_document(self) -> None:
        self.set_status(self.hidden_doc, DocumentStatus.INDEXING.value)
        llm = ScriptedLLM(lambda messages: "Quokkas smile on Rottnest island [S1].")
        with self.db() as session:
            user = session.scalars(select(User).where(User.id == self.a_id)).one()
            course, scope = self.scoped.resolve_scope(session, user, self.a_course)
            service = AnswerService(self.scoped.bind(session, user, course, scope), llm)
            answer = service.answer(HIDDEN_QUERY, user_id=self.a_id, course_id=self.a_course)
        prompts = "\n".join(m.content for call in llm.calls for m in call)
        self.assertNotIn("Quokka marsupials smile", prompts)
        self.assertNotIn(self.hidden_doc, {c.source.document_uid for c in answer.citations})
        self.assertNotIn(self.hidden_doc, {s.document_uid for s in answer.sources})
        self.assertTrue(answer.refused or all(c.source.document_uid == self.ready_doc for c in answer.citations))


class LiveIndexingRaceTests(ReadyOnlyCase):
    def test_g3_rdy_03_search_during_indexing_sees_nothing_until_ready(self) -> None:
        late = self.upload_ok(self.a, self.a_token, self.a_course,
                              ("koala.pdf", fx.pdf_bytes(text="Koala eucalyptus leaves digestion sleep. " * 6)))[0]["id"]
        container = self.app.state.ai
        real_indexing = container.indexing
        seen: dict[str, Any] = {}

        class SearchingIndexer:
            def __init__(inner) -> None:
                inner.real = real_indexing()

            def index(inner, chunks: Any, **kwargs: Any) -> Any:
                report = inner.real.index(chunks, **kwargs)  # vectors written, status still "indexing"
                with self.db() as session:
                    seen["status"] = session.scalar(select(Document.status).where(Document.id == late))
                seen["vectors"] = len(self.vector_records(late))
                seen["during"] = self.search(self.a_id, self.a_course, "koala eucalyptus digestion")
                return report

        container.indexing = SearchingIndexer
        try:
            self.process()
        finally:
            container.indexing = real_indexing
        self.assertEqual(seen["status"], "indexing")
        self.assertGreater(seen["vectors"], 0)
        self.assertNotIn(late, {h.document_uid for h in seen["during"].result.hits})
        self.assertNotIn(late, seen["during"].scope)
        after = self.search(self.a_id, self.a_course, "koala eucalyptus digestion")
        self.assertIn(late, {h.document_uid for h in after.result.hits})


class EmptyScopeTests(M3Case):
    def test_g3_rdy_05_no_ready_document_means_no_store_query_and_no_model_call(self) -> None:
        queued = self.upload_ok(self.a, self.a_token, self.a_course, ("q.pdf", fx.pdf_bytes(text=HIDDEN_TEXT)))[0]["id"]
        self.process()
        with self.db() as session:
            session.execute(update(Document).where(Document.id == queued).values(status="embedding"))
            session.commit()
        calls = {"n": 0}
        original_query = self.vectors.query

        def counting_query(*args: Any, **kwargs: Any) -> Any:
            calls["n"] += 1
            return original_query(*args, **kwargs)

        self.vectors.query = counting_query  # type: ignore[method-assign]
        try:
            scoped = self.search(self.a_id, self.a_course, HIDDEN_QUERY)
            llm = ScriptedLLM(["Quokkas smile [S1]."])
            with self.db() as session:
                user = session.scalars(select(User).where(User.id == self.a_id)).one()
                course, scope = self.scoped.resolve_scope(session, user, self.a_course)
                answer = AnswerService(self.scoped.bind(session, user, course, scope), llm).answer(
                    HIDDEN_QUERY, user_id=self.a_id, course_id=self.a_course)
        finally:
            self.vectors.query = original_query  # type: ignore[method-assign]
        self.assertEqual(calls["n"], 0)
        self.assertEqual((scoped.reason, scoped.result.hits), (NO_READY_DOCUMENTS, []))
        self.assertTrue(answer.refused)
        self.assertEqual(answer.refusal_reason, "no_results")
        self.assertEqual(llm.calls, [])


class StaticScopeRuleTests(M3Case):
    with_users = False

    def test_g3_rdy_07_raw_retrieval_is_reachable_only_through_the_scoped_layer(self) -> None:
        allowed = {ROOT / "backend/app/services/retrieval.py", ROOT / "backend/app/services/ai_container.py"}
        offenders = []
        for path in sorted((ROOT / "backend" / "app").rglob("*.py")):
            if path in allowed:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "retrieval":
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} .retrieval()")
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("ai.retrieval"):
                    names = {a.name for a in node.names}
                    if "RetrievalService" in names:
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} imports RetrievalService")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "AnswerService":
                    source = path.read_text(encoding="utf-8")
                    if "BoundRetrieval" not in source and ".bind(" not in source:
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} AnswerService without BoundRetrieval")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    import unittest

    unittest.main()

"""Combined summaries (migration 0008): one summary grounded in several ready documents of one course.

Covers: one and several documents, the "all ready files" request, validation (empty, duplicates, maximum), isolation
(missing, other course, other user), readiness, mixed PDF / DOCX / PPTX, citation and section attribution per document,
reuse of an identical in-flight request, deletion with a source document, and that single-document summaries and quizzes
keep working unchanged.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import update

from backend.app.db.models import CourseSummary, CourseSummarySource, Document, GenerationJob, Summary
from backend.app.services.generation import MAX_SUMMARY_DOCUMENTS
from backend.tests import m2_fixtures as fx
from backend.tests.m4_base import FACTS, M4Case, QuizModel, summary_reply


class CourseSummaryCase(M4Case):
    def setUp(self) -> None:
        super().setUp()
        self.deck_id = self.deck(self.a, self.a_token, self.a_course, "cells.pptx", [FACTS[0], FACTS[1]])
        self.pdf_id = self.pdf(self.a, self.a_token, self.a_course, "nerves.pdf", [FACTS[2], FACTS[3]])
        self.llm = self.use(lambda messages: summary_reply(messages) if "study summary" in messages[0].content
                            else QuizModel()(messages))

    def post(self, client: Any, token: str, course_id: str, **body: Any) -> Any:
        return client.post(f"/api/v1/courses/{course_id}/summaries", json=body, headers=self.bearer(token))

    def get(self, client: Any, token: str, summary_id: str) -> Any:
        return client.get(f"/api/v1/summaries/{summary_id}", headers=self.bearer(token))

    def combined_ok(self, document_ids: list[str]) -> dict[str, Any]:
        response = self.post(self.a, self.a_token, self.a_course, document_ids=document_ids)
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["status"], "generating")
        self.generate()
        view = self.get(self.a, self.a_token, response.json()["id"])
        self.assertEqual(view.status_code, 200, view.text)
        return dict(view.json())

    def assert_error(self, response: Any, status: int, code: str) -> None:
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json()["type"], f"about:blank#{code}")


class CombinedSummaryTests(CourseSummaryCase):
    def test_g6_cs_01_one_document(self) -> None:
        view = self.combined_ok([self.deck_id])
        self.assertEqual(view["status"], "ready")
        self.assertEqual([s["document_id"] for s in view["source_documents"]], [self.deck_id])
        self.assertEqual({c["document_id"] for c in view["citations"]}, {self.deck_id})
        self.assertEqual(view["title"], "Summary of cells.pptx")

    def test_g6_cs_02_several_documents_one_summary_attributed_per_document(self) -> None:
        view = self.combined_ok([self.pdf_id, self.deck_id])
        self.assertEqual(view["status"], "ready")
        self.assertEqual([s["document_id"] for s in view["source_documents"]], [self.pdf_id, self.deck_id])
        self.assertEqual([s["file_name"] for s in view["source_documents"]], ["nerves.pdf", "cells.pptx"])
        self.assertEqual(self.count(CourseSummary), 1)  # one combined summary, not one per document
        self.assertEqual(self.count(Summary), 0)  # and no single-document summaries made on the side
        by_number = {c["number"]: c for c in view["citations"]}
        self.assertEqual({c["document_id"] for c in view["citations"]}, {self.pdf_id, self.deck_id})
        for section in view["sections"]:
            self.assertIn(section["document_id"], (self.pdf_id, self.deck_id))
            self.assertEqual(section["file_name"], "nerves.pdf" if section["document_id"] == self.pdf_id
                             else "cells.pptx")
            self.assertTrue(section["citations"])
            for number in section["citations"]:  # every citation of a section points into that section's document
                self.assertEqual(by_number[number]["document_id"], section["document_id"])
                self.assertTrue(by_number[number]["citation_label"])
        # the reader's order is kept: the PDF's sections come first
        self.assertEqual(view["sections"][0]["document_id"], self.pdf_id)
        self.assertEqual(view["title"], "Summary of 2 files")

    def test_g6_cs_03_model_calls_never_mix_documents(self) -> None:
        self.combined_ok([self.pdf_id, self.deck_id])
        for call in self.llm.calls:
            text = call[-1].content
            self.assertFalse("Mitochondria" in text and "Neurons" in text, "one batch held two documents")

    def test_g6_cs_04_all_ready_files_mixed_types(self) -> None:
        docx_id = str(self.upload_ok(self.a, self.a_token, self.a_course, ("notes.docx", fx.docx_bytes(3)))[0]["id"])
        self.process()
        ids = [self.pdf_id, docx_id, self.deck_id]
        view = self.combined_ok(ids)
        self.assertEqual(view["status"], "ready")
        self.assertEqual([s["document_id"] for s in view["source_documents"]], ids)
        self.assertEqual({s["document_id"] for s in view["sections"]}, set(ids))

    def test_g6_cs_05_validation(self) -> None:
        jobs = self.jobs()
        self.assert_error(self.post(self.a, self.a_token, self.a_course, document_ids=[]), 422, "validation_error")
        self.assert_error(self.post(self.a, self.a_token, self.a_course, document_ids=[self.pdf_id, self.pdf_id]),
                          422, "duplicate_documents")
        too_many = [str(uuid.uuid4()) for _ in range(MAX_SUMMARY_DOCUMENTS + 1)]
        self.assert_error(self.post(self.a, self.a_token, self.a_course, document_ids=too_many), 422,
                          "too_many_documents")
        self.assertEqual(self.post(self.a, self.a_token, self.a_course).status_code, 422)  # document_ids is required
        response = self.a.post(f"/api/v1/courses/{self.a_course}/summaries", headers=self.bearer(self.a_token),
                               json={"document_ids": [self.pdf_id], "course_id": self.b_course})
        self.assertEqual(response.status_code, 422, response.text)  # scope fields are rejected
        self.assertEqual(self.jobs(), jobs)

    def test_g6_cs_06_missing_foreign_and_other_course_documents_are_one_404(self) -> None:
        other_course = self.create_course(self.a_token, "Second course")
        elsewhere = self.doc(self.a, self.a_token, other_course, "elsewhere.pdf", FACTS[0])
        foreign = self.doc(self.b, self.b_token, self.b_course, "foreign.pdf", FACTS[1])
        jobs, calls = self.jobs(), len(self.llm.calls)
        for raw in (str(uuid.uuid4()), "not-an-id", elsewhere, foreign):
            with self.subTest(raw=raw[:12]):
                self.assert_same_404(self.post(self.a, self.a_token, self.a_course,
                                               document_ids=[self.pdf_id, raw]), self.a_token)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            self.assert_same_404(self.post(self.b, self.b_token, self.a_course, document_ids=[self.pdf_id]),
                                 self.b_token)
        self.assertEqual((self.jobs(), len(self.llm.calls)), (jobs, calls))

    def test_g6_cs_07_processing_and_failed_documents_are_refused(self) -> None:
        for status in ("embedding", "failed"):
            with self.subTest(status=status):
                with self.db() as session:
                    session.execute(update(Document).where(Document.id == self.deck_id).values(status=status))
                    session.commit()
                self.assert_error(self.post(self.a, self.a_token, self.a_course,
                                            document_ids=[self.pdf_id, self.deck_id]), 409, "document_not_ready")
        self.assertEqual(self.count(CourseSummary), 0)

    def test_g6_cs_08_a_repeated_request_reuses_the_generation_in_flight(self) -> None:
        first = self.post(self.a, self.a_token, self.a_course, document_ids=[self.pdf_id, self.deck_id])
        again = self.post(self.a, self.a_token, self.a_course, document_ids=[self.pdf_id, self.deck_id])
        self.assertEqual((first.status_code, again.status_code), (202, 200))
        self.assertEqual(first.json()["id"], again.json()["id"])
        self.assertEqual(self.count(CourseSummary), 1)
        other_order = self.post(self.a, self.a_token, self.a_course, document_ids=[self.deck_id, self.pdf_id])
        self.assertEqual(other_order.status_code, 202)  # a different reading order is a different summary

    def test_g6_cs_09_other_users_cannot_read_list_or_delete(self) -> None:
        view = self.combined_ok([self.pdf_id, self.deck_id])
        for method in ("get", "delete"):
            with self.subTest(method=method), self.assertLogs("intellistudy.security", level="WARNING"):
                response = getattr(self.b, method)(f"/api/v1/summaries/{view['id']}", headers=self.bearer(self.b_token))
                self.assert_same_404(response, self.b_token)
        listed = self.a.get(f"/api/v1/courses/{self.a_course}/summaries", headers=self.bearer(self.a_token))
        self.assertEqual([s["id"] for s in listed.json()["items"]], [view["id"]])
        self.assertEqual(self.b.get(f"/api/v1/courses/{self.b_course}/summaries",
                                    headers=self.bearer(self.b_token)).json()["items"], [])

    def test_g6_cs_10_deleting_a_source_document_deletes_the_combined_summary(self) -> None:
        view = self.combined_ok([self.pdf_id, self.deck_id])
        queued = self.post(self.a, self.a_token, self.a_course, document_ids=[self.deck_id, self.pdf_id]).json()
        response = self.a.delete(f"/api/v1/documents/{self.deck_id}", headers=self.bearer(self.a_token))
        self.assertEqual(response.status_code, 204, response.text)
        for summary_id in (view["id"], queued["id"]):
            self.assert_same_404(self.get(self.a, self.a_token, summary_id), self.a_token)
        self.assertEqual(self.count(CourseSummary), 0)
        self.assertEqual(self.count(CourseSummarySource), 0)
        self.assertEqual(self.count(GenerationJob, GenerationJob.course_summary_id.is_not(None)), 0)
        self.assertEqual(self.generate(), 0)

    def test_g6_cs_11_owner_can_delete(self) -> None:
        view = self.combined_ok([self.pdf_id])
        response = self.a.delete(f"/api/v1/summaries/{view['id']}", headers=self.bearer(self.a_token))
        self.assertEqual(response.status_code, 204, response.text)
        self.assert_same_404(self.get(self.a, self.a_token, view["id"]), self.a_token)

    def test_g6_cs_12_single_document_summaries_and_multi_document_quizzes_are_unchanged(self) -> None:
        single = self.summary_ok(self.a, self.a_token, self.deck_id)
        self.assertEqual(single["status"], "ready")
        self.assertEqual({c["document_id"] for c in single["citations"]}, {self.deck_id})
        for section in single["sections"]:  # new attribution fields are filled for new single summaries too
            self.assertEqual((section["document_id"], section["file_name"]), (self.deck_id, "cells.pptx"))
        quiz = self.quiz_ok(self.a, self.a_token, self.a_course, document_ids=[self.pdf_id, self.deck_id],
                            question_count=6)
        self.assertEqual(sorted(quiz["source_document_ids"]), sorted([self.pdf_id, self.deck_id]))
        self.assertEqual(quiz["status"], "ready")

    def test_g6_cs_13_a_source_that_stops_being_ready_fails_the_generation_explicitly(self) -> None:
        response = self.post(self.a, self.a_token, self.a_course, document_ids=[self.pdf_id, self.deck_id])
        with self.db() as session:
            session.execute(update(Document).where(Document.id == self.deck_id).values(status="failed"))
            session.commit()
        self.generate()
        view = self.get(self.a, self.a_token, response.json()["id"]).json()
        self.assertEqual((view["status"], view["error_code"], view["sections"]), ("failed", "document_not_ready", []))


# ------------------------------------------------------------------ migration 0008 and the schema guard
def _migrate_to(url: str, revision: str, *, down: bool = False) -> None:
    from alembic import command

    from backend.app.db.migrate import alembic_config
    from backend.app.db.session import create_db_engine

    engine = create_db_engine(url)
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            (command.downgrade if down else command.upgrade)(config, revision)
    finally:
        engine.dispose()


def _revision(url: str) -> str | None:
    from backend.app.db.migrate import current_revision
    from backend.app.db.session import create_db_engine

    engine = create_db_engine(url)
    try:
        with engine.connect() as connection:
            return current_revision(connection)
    finally:
        engine.dispose()


class SchemaGuardTests(CourseSummaryCase):
    def test_g6_cs_14_upgrading_a_0007_database_with_data_keeps_summaries_and_quizzes(self) -> None:
        url = self.settings.database_url
        single = self.summary_ok(self.a, self.a_token, self.deck_id)
        quiz = self.quiz_ok(self.a, self.a_token, self.a_course, document_ids=[self.pdf_id, self.deck_id], question_count=6)
        _migrate_to(url, "0007_quiz_attempts", down=True)  # the schema the dev database had before this change
        self.assertEqual(_revision(url), "0007_quiz_attempts")
        _migrate_to(url, "head")
        self.assertEqual(_revision(url), "0008_course_summaries")
        self.assertEqual(self.get_summary(self.a, self.a_token, self.deck_id).json()["sections"], single["sections"])
        self.assertEqual(self.get_quiz(self.a, self.a_token, quiz["id"]).json()["id"], quiz["id"])
        self.assertEqual(self.combined_ok([self.pdf_id, self.deck_id])["status"], "ready")

    def test_g6_cs_15_a_database_behind_the_code_is_reported_instead_of_failing_as_a_bare_500(self) -> None:
        from fastapi.testclient import TestClient

        from backend.app.main import create_app

        url = self.settings.database_url
        _migrate_to(url, "0007_quiz_attempts", down=True)
        app = create_app(self.settings, clock=self.clock, ai=self.make_ai())
        with self.assertLogs("backend.app.main", level="ERROR") as logs, TestClient(app, base_url="https://testserver") as client:
            self.assertEqual(client.get("/api/v1/health").json()["database"], "outdated")
            response = client.get(f"/api/v1/documents/{self.deck_id}/summary", headers=self.bearer(self.a_token))
            self.assertEqual(response.status_code, 503, response.text)
            body = response.json()
            self.assertEqual(body["type"], "about:blank#database_outdated")
            self.assertNotIn("course_summary_id", response.text)  # no SQL or schema detail reaches the client
            self.assertIn("migrations", body["detail"])
            _migrate_to(url, "head")
            self.assertEqual(client.get("/api/v1/health").json()["database"], "ok")  # recovers without a restart
            self.assertEqual(client.get(f"/api/v1/documents/{self.deck_id}/summary",
                                        headers=self.bearer(self.a_token)).status_code, 404)
        self.assertTrue(any("python -m backend.app.db.migrate" in line for line in logs.output))

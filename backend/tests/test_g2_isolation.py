"""M2 gate: cross-user document isolation (G2-ISO-*). Contract I-05..I-08, I-14, R-03, R-08, R-09, VEC-01/02."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

from sqlalchemy import select

from backend.app.db.models import Document, ProcessingJob
from backend.app.services.sandbox import run_parse
from backend.tests import m2_fixtures as fx
from backend.tests.m2_base import M2Case


class DocumentIsolationTests(M2Case):
    def setUp(self) -> None:
        super().setUp()
        self.a_doc = self.upload_ok(self.a, self.a_token, self.a_course, ("a-private.pdf", fx.pdf_bytes()))[0]["id"]
        self.process()

    def test_g2_iso_01_list_of_another_users_course(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING"):
            response = self.b.get(f"/api/v1/courses/{self.a_course}/documents", headers=self.bearer(self.b_token))
        self.assert_same_404(response, self.b_token)
        own = self.b.get(f"/api/v1/courses/{self.b_course}/documents", headers=self.bearer(self.b_token)).json()
        self.assertEqual(own["items"], [])

    def test_g2_iso_02_read_of_another_users_document(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING") as logs:
            response = self.b.get(f"/api/v1/documents/{self.a_doc}", headers=self.bearer(self.b_token))
        self.assert_same_404(response, self.b_token)
        self.assertIn("ownership_mismatch", [getattr(r, "security_event", {}).get("event") for r in logs.records])

    def test_g2_iso_03_download_of_another_users_document(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING"):
            response = self.b.get(f"/api/v1/documents/{self.a_doc}/file", headers=self.bearer(self.b_token))
        self.assert_same_404(response, self.b_token)
        self.assertNotIn(b"%PDF", response.content)

    def test_g2_iso_04_delete_or_retry_of_another_users_document(self) -> None:
        for method, path in (("DELETE", f"/api/v1/documents/{self.a_doc}"), ("POST", f"/api/v1/documents/{self.a_doc}/retry")):
            with self.subTest(method=method), self.assertLogs("intellistudy.security", level="WARNING"):
                self.assert_same_404(self.b.request(method, path, headers=self.bearer(self.b_token)), self.b_token)
        self.assertEqual(self.document(self.a_token, self.a_doc)["status"], "ready")
        self.assertTrue(self.vector_records(self.a_doc))
        self.assertTrue(self.stored_dir(self.a_id, self.a_doc).exists())

    def test_g2_iso_05_random_and_malformed_document_ids(self) -> None:
        for raw in (str(uuid.uuid4()), "123", self.a_doc.upper(), "x" * 500):
            for path in (f"/api/v1/documents/{raw}", f"/api/v1/documents/{raw}/file"):
                with self.subTest(path=path[:40]):
                    self.assert_same_404(self.a.get(path, headers=self.bearer(self.a_token)), self.a_token)

    def test_g2_iso_06_vector_and_parent_metadata_come_from_the_row(self) -> None:
        with self.db() as session:
            row = session.scalars(select(Document).where(Document.id == self.a_doc)).one()
        records = self.vector_records(self.a_doc)
        self.assertTrue(records)
        for record in records:
            self.assertEqual((record["user_id"], record["course_id"], record["document_uid"]),
                             (row.owner_id, row.course_id, row.id))
            self.assertTrue(record["id"].startswith(f"{row.id}:"))
            self.assertEqual(record["file_name"], row.file_name)  # the user's name, never the stored "original.pdf"
        keys = sorted(self.parent_keys(self.a_doc))
        self.assertTrue(keys)
        self.assertEqual(len(self.parents.get_many(keys, user_id=self.a_id, course_id=self.a_course)), len(keys))
        self.assertEqual(self.parents.get_many(keys, user_id=self.b_id, course_id=self.b_course), {})

    def test_g2_iso_07_identical_bytes_from_two_users_stay_disjoint(self) -> None:
        data = fx.pdf_bytes(text="shared lecture " * 30)
        a2 = self.upload_ok(self.a, self.a_token, self.a_course, ("shared.pdf", data))[0]["id"]
        b2 = self.upload_ok(self.b, self.b_token, self.b_course, ("shared.pdf", data))[0]["id"]
        self.process()
        a_ids = {r["id"] for r in self.vector_records(a2)}
        b_ids = {r["id"] for r in self.vector_records(b2)}
        self.assertTrue(a_ids and b_ids)
        self.assertEqual(a_ids & b_ids, set())
        self.assertTrue(all(r["user_id"] == self.b_id for r in self.vector_records(b2)))
        self.assertEqual(self.parent_keys(a2) & self.parent_keys(b2), set())

    def test_g2_iso_08_delete_removes_vectors_parents_file_and_rows(self) -> None:
        b_doc = self.upload_ok(self.b, self.b_token, self.b_course, ("b.pdf", fx.pdf_bytes(text="bob " * 40)))[0]["id"]
        self.process()
        response = self.a.delete(f"/api/v1/documents/{self.a_doc}", headers=self.bearer(self.a_token))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.vector_records(self.a_doc), [])
        self.assertEqual(self.parent_keys(self.a_doc), set())
        self.assertFalse(self.stored_dir(self.a_id, self.a_doc).exists())
        with self.db() as session:
            self.assertIsNone(session.scalar(select(Document.id).where(Document.id == self.a_doc)))
            self.assertEqual(session.scalars(select(ProcessingJob).where(ProcessingJob.document_id == self.a_doc)).all(), [])
        self.assert_same_404(self.a.get(f"/api/v1/documents/{self.a_doc}", headers=self.bearer(self.a_token)), self.a_token)
        self.assertTrue(self.vector_records(b_doc))  # B untouched
        self.assertTrue(self.stored_dir(self.b_id, b_doc).exists())

    def test_g2_iso_09_delete_course_removes_all_of_its_documents(self) -> None:
        second = self.upload_ok(self.a, self.a_token, self.a_course, ("two.docx", fx.docx_bytes()))[0]["id"]
        queued = self.upload_ok(self.a, self.a_token, self.a_course, ("three.pptx", fx.pptx_bytes()))[0]["id"]
        self.process()
        b_doc = self.upload_ok(self.b, self.b_token, self.b_course, ("b.pdf", fx.pdf_bytes(text="bob " * 40)))[0]["id"]
        self.process()
        late = self.upload_ok(self.a, self.a_token, self.a_course, ("late.pdf", fx.pdf_bytes(text="late " * 40)))[0]["id"]
        response = self.a.delete(f"/api/v1/courses/{self.a_course}", headers=self.bearer(self.a_token))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.process(), 0)  # the queued job of the course was cancelled
        for doc in (self.a_doc, second, queued, late):
            self.assertEqual(self.vector_records(doc), [], doc)
            self.assertEqual(self.parent_keys(doc), set())
            self.assertFalse(self.stored_dir(self.a_id, doc).exists())
        with self.db() as session:
            self.assertEqual(session.scalars(select(Document).where(Document.course_id == self.a_course)).all(), [])
        self.assertTrue(self.vector_records(b_doc))
        self.assertEqual(self.document(self.b_token, b_doc)["status"], "ready")

    def test_g2_iso_10_sandbox_output_claiming_another_scope_is_rejected(self) -> None:
        def lying_parser(path: Any, **kwargs: Any) -> Any:
            outcome = run_parse(path, **kwargs)
            outcome.children = [dataclasses.replace(c, user_id=self.b_id) for c in outcome.children]
            return outcome

        self.app.state.jobs._parser = lying_parser
        doc = self.upload_ok(self.a, self.a_token, self.a_course, ("x.pdf", fx.pdf_bytes(text="lie " * 40)))[0]["id"]
        with self.assertLogs("intellistudy.security", level="WARNING") as logs:
            self.process()
        state = self.document(self.a_token, doc)
        self.assertEqual((state["status"], state["error_code"]), ("failed", "invalid_output"))
        self.assertEqual(self.vector_records(doc), [])
        self.assertIn("chunk_scope_mismatch", [getattr(r, "security_event", {}).get("event") for r in logs.records])


if __name__ == "__main__":
    import unittest

    unittest.main()

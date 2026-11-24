"""M2 gate: job queue and processing lifecycle (G2-JOB-*). Contract OWN-10, RET-05, ISO-03, FR-UPL-05."""

from __future__ import annotations

import threading
import time
from typing import Any

from sqlalchemy import select, update

from backend.app.db.models import Document, ProcessingJob
from backend.app.services.sandbox import run_parse
from backend.tests import m2_fixtures as fx
from backend.tests.m2_base import M2Case


class JobLifecycleTests(M2Case):
    def job(self, document_id: str) -> ProcessingJob:
        with self.db() as session:
            job = session.scalars(select(ProcessingJob).where(ProcessingJob.document_id == document_id)
                                  .order_by(ProcessingJob.created_at.desc())).first()
            assert job is not None
            return job

    def test_g2_job_01_queued_to_ready(self) -> None:
        doc = self.upload_ok(self.a, self.a_token, self.a_course, ("lecture.pdf", fx.pdf_bytes(pages=3)))[0]
        self.assertEqual((doc["status"], doc["progress"], doc["duplicate"]), ("queued", 0, False))
        self.assertEqual(self.vector_records(doc["id"]), [])  # nothing indexed before processing
        self.assertEqual(self.process(), 1)
        state = self.document(self.a_token, doc["id"])
        self.assertEqual((state["status"], state["progress"], state["page_count"]), ("ready", 100, 3))
        self.assertGreater(state["chunk_count"], 0)
        self.assertIsNotNone(state["ready_at"])
        self.assertEqual(len(self.vector_records(doc["id"])), state["chunk_count"])
        self.assertEqual(self.job(doc["id"]).status, "done")
        listed = self.a.get(f"/api/v1/courses/{self.a_course}/documents", headers=self.bearer(self.a_token)).json()
        self.assertEqual([d["id"] for d in listed["items"]], [doc["id"]])

    def test_g2_job_02_failed_documents_can_be_retried_others_cannot(self) -> None:
        bad = self.upload_ok(self.a, self.a_token, self.a_course, ("m.docx", fx.macro_docx()))[0]["id"]
        good = self.upload_ok(self.a, self.a_token, self.a_course, ("g.pdf", fx.pdf_bytes()))[0]["id"]
        self.process()
        self.assertEqual(self.document(self.a_token, bad)["status"], "failed")
        retried = self.a.post(f"/api/v1/documents/{bad}/retry", headers=self.bearer(self.a_token))
        self.assertEqual(retried.status_code, 202)
        self.assertEqual((retried.json()["status"], retried.json()["error_code"]), ("queued", None))
        self.process()
        self.assertEqual(self.document(self.a_token, bad)["error_code"], "macro_document")
        conflict = self.a.post(f"/api/v1/documents/{good}/retry", headers=self.bearer(self.a_token))
        self.assertEqual(conflict.status_code, 409)

    def test_g2_job_03_delete_while_queued_cancels_the_job(self) -> None:
        doc = self.upload_ok(self.a, self.a_token, self.a_course, ("q.pdf", fx.pdf_bytes()))[0]["id"]
        self.assertEqual(self.a.delete(f"/api/v1/documents/{doc}", headers=self.bearer(self.a_token)).status_code, 204)
        self.assertEqual(self.process(), 0)
        self.assertFalse(self.stored_dir(self.a_id, doc).exists())
        self.assertEqual(self.vector_records(doc), [])

    def test_g2_job_04_delete_while_running_is_finished_by_the_runner(self) -> None:
        doc = self.upload_ok(self.a, self.a_token, self.a_course, ("r.pdf", fx.pdf_bytes()))[0]["id"]

        def delete_mid_run(path: Any, **kwargs: Any) -> Any:
            outcome = run_parse(path, **kwargs)
            response = self.a.delete(f"/api/v1/documents/{doc}", headers=self.bearer(self.a_token))
            self.assertEqual(response.status_code, 204)  # marked deleting; the running job finishes the purge
            return outcome

        self.app.state.jobs._parser = delete_mid_run
        self.process()
        self.assertEqual(self.vector_records(doc), [])
        self.assertEqual(self.parent_keys(doc), set())
        self.assertFalse(self.stored_dir(self.a_id, doc).exists())
        with self.db() as session:
            self.assertIsNone(session.scalar(select(Document.id).where(Document.id == doc)))

    def test_g2_job_05_interrupted_jobs_are_requeued_on_start(self) -> None:
        doc = self.upload_ok(self.a, self.a_token, self.a_course, ("c.pdf", fx.pdf_bytes()))[0]["id"]
        with self.db() as session:  # simulate a crash mid-job
            session.execute(update(ProcessingJob).where(ProcessingJob.document_id == doc).values(status="running"))
            session.execute(update(Document).where(Document.id == doc).values(status="embedding", progress=55))
            session.commit()
        self.assertEqual(self.process(), 0)  # a running job is never picked twice
        self.assertEqual(self.app.state.jobs.recover(), 1)
        self.assertEqual(self.document(self.a_token, doc)["status"], "queued")
        self.process()
        self.assertEqual(self.document(self.a_token, doc)["status"], "ready")

    def test_g2_job_06_infrastructure_errors_retry_once_and_leave_no_index(self) -> None:
        calls = {"n": 0}

        def flaky(path: Any, **kwargs: Any) -> Any:
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("transient")
            return run_parse(path, **kwargs)

        self.app.state.jobs._parser = flaky
        doc = self.upload_ok(self.a, self.a_token, self.a_course, ("f.pdf", fx.pdf_bytes()))[0]["id"]
        self.process()
        self.assertEqual(calls["n"], 2)
        self.assertEqual(self.document(self.a_token, doc)["status"], "ready")

        def broken_index(*_: Any, **__: Any) -> Any:
            raise RuntimeError("index down")

        self.app.state.jobs._parser = run_parse
        original = self.app.state.ai.indexing
        self.app.state.ai.indexing = lambda: type("I", (), {"index": broken_index})()
        try:
            doc2 = self.upload_ok(self.a, self.a_token, self.a_course, ("g.pdf", fx.pdf_bytes(text="g " * 50)))[0]["id"]
            self.process()
        finally:
            self.app.state.ai.indexing = original
        state = self.document(self.a_token, doc2)
        self.assertEqual((state["status"], state["error_code"]), ("failed", "internal_error"))
        self.assertEqual(self.job(doc2).attempts, 2)
        self.assertEqual(self.vector_records(doc2), [])
        self.assertNotIn("index down", str(state))

    def test_g2_job_07_a_job_is_claimed_exactly_once(self) -> None:
        self.upload_ok(self.a, self.a_token, self.a_course, ("once.pdf", fx.pdf_bytes()))
        calls = {"n": 0}
        lock = threading.Lock()

        def slow(path: Any, **kwargs: Any) -> Any:
            with lock:
                calls["n"] += 1
            time.sleep(0.5)
            return run_parse(path, **kwargs)

        self.app.state.jobs._parser = slow
        threads = [threading.Thread(target=self.app.state.jobs.run_next) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(calls["n"], 1)

    def test_g2_job_08_failed_or_deleted_documents_leave_nothing_retrievable(self) -> None:
        failed = self.upload_ok(self.a, self.a_token, self.a_course, ("bomb.docx", fx.zip_bomb_docx()))[0]["id"]
        ready = self.upload_ok(self.a, self.a_token, self.a_course, ("ok.pdf", fx.pdf_bytes()))[0]["id"]
        self.process()
        self.assertEqual(self.vector_records(failed), [])
        self.assertTrue(self.vector_records(ready))
        statuses = {d["id"]: d["status"] for d in self.a.get(
            f"/api/v1/courses/{self.a_course}/documents", headers=self.bearer(self.a_token)).json()["items"]}
        self.assertEqual(statuses, {failed: "failed", ready: "ready"})


if __name__ == "__main__":
    import unittest

    unittest.main()

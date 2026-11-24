"""M2 gate: upload security (G2-UPL-*) and file storage (G2-FILE-*). See docs/SECURITY_MERGE_GATE.md, M2 section."""

from __future__ import annotations

import json
import os
import stat
import threading
import time
from pathlib import Path
from typing import Any
from unittest import mock

from sqlalchemy import func, select

from backend.app.db.models import Document
from backend.app.services.documents import REASONS
from backend.app.services.sandbox import TIMED_OUT, TOO_LARGE, child_environment, run_parse
from backend.app.services.storage import FileStorage, StorageError, display_name
from backend.tests import m2_fixtures as fx
from backend.tests.m2_base import M2Case

PROBES = "backend.tests.sandbox_probes"


class UploadCase(M2Case):
    def documents_count(self) -> int:
        with self.db() as session:
            return int(session.scalar(select(func.count()).select_from(Document)) or 0)

    def reasons(self, response: Any) -> list[str]:
        return [f["reason"] for f in response.json().get("files", [])]

    def failed_with(self, name: str, data: bytes, expected: str) -> dict[str, Any]:
        doc = self.upload_ok(self.a, self.a_token, self.a_course, (name, data))[0]
        self.process()
        state = self.document(self.a_token, doc["id"])
        self.assertEqual((state["status"], state["error_code"]), ("failed", expected), state)
        self.assertEqual(state["error_message"], REASONS[expected])
        self.assertEqual(self.vector_records(doc["id"]), [])
        self.assertEqual(self.parent_keys(doc["id"]), set())
        return state


class SmallLimitTests(UploadCase):
    def settings_overrides(self) -> dict[str, Any]:
        return {**super().settings_overrides(), "max_upload_bytes": 64 * 1024, "storage_quota_bytes": 60_000}

    def test_g2_upl_01_oversize_upload_is_413_and_nothing_is_stored(self) -> None:
        big = fx.pdf_bytes() + b"%" + os.urandom(100 * 1024)
        response = self.upload(self.a, self.a_token, self.a_course, ("big.pdf", big))
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["type"], "about:blank#file_too_large")
        self.assertEqual(self.incoming_files(), [])
        self.assertEqual(self.documents_count(), 0)

        boundary = "xBOUNDARYx"
        def body():  # chunked: no Content-Length
            yield (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"c.pdf\"\r\n"
                   "Content-Type: application/pdf\r\n\r\n").encode()
            for _ in range(20):
                yield b"%PDF-" + bytes(16 * 1024)
            yield f"\r\n--{boundary}--\r\n".encode()
        chunked = self.a.post(f"/api/v1/courses/{self.a_course}/documents", content=body(),
                              headers={**self.bearer(self.a_token), "Content-Type": f"multipart/form-data; boundary={boundary}"})
        self.assertEqual(chunked.status_code, 413)
        self.assertEqual(self.incoming_files(), [])

        declared = self.a.post(f"/api/v1/courses/{self.a_course}/documents", content=b"x",
                               headers={**self.bearer(self.a_token), "Content-Length": str(10**10),
                                        "Content-Type": f"multipart/form-data; boundary={boundary}"})
        self.assertEqual(declared.status_code, 413)

    def test_g2_upl_10_too_many_files_and_quota(self) -> None:
        eleven = [(f"f{i}.pdf", fx.pdf_bytes(text=f"doc {i} " * 20)) for i in range(11)]
        response = self.upload(self.a, self.a_token, self.a_course, *eleven)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["type"], "about:blank#too_many_files")
        self.assertEqual(self.incoming_files(), [])
        self.upload_ok(self.a, self.a_token, self.a_course, ("a.docx", fx.docx_bytes()))  # ~37 KB of 60 KB
        over = self.upload(self.a, self.a_token, self.a_course, ("b.docx", fx.docx_bytes(paragraphs=4)))
        self.assertEqual(over.status_code, 413)
        self.assertEqual(over.json()["type"], "about:blank#quota_exceeded")
        self.assertEqual(self.documents_count(), 1)
        self.assertEqual(self.incoming_files(), [])


class TypeTests(UploadCase):
    def test_g2_upl_02_content_must_match_the_extension(self) -> None:
        cases = {"x.pdf": fx.docx_bytes(), "x.docx": fx.pdf_bytes(), "page.pdf": b"<html><script>1</script></html>",
                 "tool.pdf": b"MZ\x90\x00" + bytes(200), "img.pptx": fx.small_png()}
        for name, data in cases.items():
            with self.subTest(name=name), self.assertLogs("intellistudy.security", level="WARNING"):
                response = self.upload(self.a, self.a_token, self.a_course, (name, data))
                self.assertEqual(response.status_code, 422)
                self.assertEqual(self.reasons(response), ["type_mismatch"])
        self.assertEqual(self.documents_count(), 0)
        self.assertEqual(self.incoming_files(), [])

    def test_g2_upl_03_legacy_and_macro_formats_are_rejected(self) -> None:
        for name in ("old.doc", "old.ppt", "macro.docm", "macro.pptm", "notes.txt", "noext"):
            with self.subTest(name=name), self.assertLogs("intellistudy.security", level="WARNING"):
                response = self.upload(self.a, self.a_token, self.a_course, (name, fx.docx_bytes()))
                self.assertEqual(response.status_code, 422)
                self.assertEqual(self.reasons(response), ["unsupported_type"])
        self.failed_with("legacy.docx", fx.ole_bytes(encrypted=False), "unsupported_type")
        self.failed_with("macro.docx", fx.macro_docx(), "macro_document")

    def test_g2_upl_04_zip_bombs_and_hostile_archives_fail_before_parsing(self) -> None:
        for name, data in {"bomb.docx": fx.zip_bomb_docx(), "traversal.docx": fx.traversal_docx(),
                           "overlap.docx": fx.overlapping_zip_docx()}.items():
            with self.subTest(name=name):
                self.failed_with(name, data, "archive_rejected")

    def test_g2_upl_05_encrypted_documents(self) -> None:
        self.failed_with("locked.pdf", fx.pdf_bytes(user_password="secret1"), "password_protected")
        self.failed_with("locked.docx", fx.ole_bytes(encrypted=True), "password_protected")
        # owner-password-only PDF: readable without a password, accepted (finding F-M2-02)
        doc = self.upload_ok(self.a, self.a_token, self.a_course, ("perms.pdf", fx.pdf_bytes(owner_password="own")))[0]
        self.process()
        self.assertEqual(self.document(self.a_token, doc["id"])["status"], "ready")

    def test_g2_upl_13_failure_reasons_are_from_the_fixed_list(self) -> None:
        state = self.failed_with("bomb.docx", fx.zip_bomb_docx(), "archive_rejected")
        text = json.dumps(state)
        for leak in ("Traceback", str(self.settings.storage_root), "/home/", "zipfile", "Error("):
            self.assertNotIn(leak, text)
        self.assertTrue(set(REASONS) >= {"unsupported_type", "type_mismatch", "password_protected", "too_many_pages",
                                         "corrupted", "unreadable", "timed_out", "archive_rejected"})
        # a child that returns an arbitrary error string cannot inject it into responses
        work = Path(self.tmp) / "probe"
        work.mkdir()
        probe = work / "in.pdf"
        probe.write_text("huge_error")
        outcome = run_parse(probe, kind="pdf", container="pdf", user_id=self.a_id, course_id=self.a_course,
                            document_id=self.a_course, settings=self.settings, work_root=work, child_module=PROBES)
        self.assertEqual(outcome.error, "invalid_output")


class PageLimitTests(UploadCase):
    def settings_overrides(self) -> dict[str, Any]:
        return {**super().settings_overrides(), "max_pages": 5}

    def test_g2_upl_06_too_many_pages_or_slides(self) -> None:
        self.failed_with("long.pdf", fx.pdf_bytes(pages=6), "too_many_pages")
        self.failed_with("long.pptx", fx.pptx_bytes(slides=6), "too_many_pages")


class ImageBombTests(UploadCase):
    def test_g2_upl_07_decompression_bomb_image_is_skipped_not_fatal(self) -> None:
        doc = self.upload_ok(self.a, self.a_token, self.a_course, ("bomb-image.pptx", fx.pptx_with_bomb_image()))[0]
        self.process()
        state = self.document(self.a_token, doc["id"])
        self.assertEqual(state["status"], "ready", state)  # text of the slides is still indexed
        self.assertGreater(state["chunk_count"], 0)
        self.assertEqual(self.client().get("/api/v1/health").status_code, 200)  # runner and API alive


class SandboxLimitTests(UploadCase):
    def settings_overrides(self) -> dict[str, Any]:
        return {**super().settings_overrides(), "parse_timeout_seconds": 3, "parse_rss_limit_bytes": 300 * 1024**2}

    def probe(self, mode: str) -> Any:
        work = Path(self.tmp) / f"probe-{mode}"
        work.mkdir()
        target = work / "input.pdf"
        target.write_text(mode)
        return run_parse(target, kind="pdf", container="pdf", user_id=self.a_id, course_id=self.a_course,
                         document_id=self.a_course, settings=self.settings, work_root=work / "w", child_module=PROBES)

    def test_g2_upl_08_hanging_or_memory_hungry_parsers_are_killed(self) -> None:
        results: dict[str, Any] = {}
        api_ok: list[int] = []

        def run(mode: str) -> None:
            results[mode] = self.probe(mode)

        with self.assertLogs("intellistudy.security", level="WARNING") as logs:
            threads = [threading.Thread(target=run, args=(m,)) for m in ("hang", "memory")]
            started = time.monotonic()
            for t in threads:
                t.start()
            while any(t.is_alive() for t in threads):
                api_ok.append(self.client().get("/api/v1/health").status_code)  # API responsive throughout
                time.sleep(0.3)
            for t in threads:
                t.join()
        self.assertEqual(results["hang"].error, TIMED_OUT)
        self.assertEqual(results["memory"].error, TOO_LARGE)
        self.assertLess(time.monotonic() - started, 30)
        self.assertTrue(api_ok and all(code == 200 for code in api_ok))
        events = {getattr(r, "security_event", {}).get("event") for r in logs.records}
        self.assertTrue({"parse_timeout", "parse_memory_limit"} <= events)
        crash = self.probe("crash")
        self.assertFalse(crash.ok)
        self.assertEqual(self.probe("bad").error, "invalid_output")


class NameAndDownloadTests(UploadCase):
    def raw_upload(self, filename: str, data: bytes) -> dict[str, Any]:
        """Multipart body built by hand, so control characters in the file name reach the server unencoded
        (HTTP clients percent-encode them)."""
        boundary = "rawBOUNDARY"
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{filename}\"\r\n"
                "Content-Type: application/pdf\r\n\r\n").encode()
        body = head + data + f"\r\n--{boundary}--\r\n".encode()
        response = self.a.post(f"/api/v1/courses/{self.a_course}/documents", content=body, headers={
            **self.bearer(self.a_token), "Content-Type": f"multipart/form-data; boundary={boundary}"})
        self.assertEqual(response.status_code, 202, response.text)
        return dict(response.json()["documents"][0])

    def test_g2_upl_09_hostile_file_names_are_display_only(self) -> None:
        names = {"../../etc/passwd.pdf": "passwd.pdf", "..\\..\\win.pdf": "win.pdf",
                 "evil\u202egnp.pdf": "evilgnp.pdf", "tab\tbell\x07zero\x00.pdf": "tabbellzero.pdf"}
        for index, (raw, shown) in enumerate(names.items()):
            with self.subTest(raw=raw):
                doc = self.raw_upload(raw, fx.pdf_bytes(text=f"file {index} " * 30))
                self.assertEqual(doc["file_name"], shown)
                stored = list(self.stored_dir(self.a_id, doc["id"]).iterdir())
                self.assertEqual([p.name for p in stored], ["original.pdf"])
        long_name = "x" * 1000 + ".pdf"
        self.assertEqual(len(display_name(long_name)), 255)
        self.assertTrue(display_name(long_name).endswith(".pdf"))
        self.assertFalse((Path(self.settings.storage_root).resolve().parent / "etc").exists())

    def test_g2_upl_12_download_is_an_attachment_with_the_verified_type(self) -> None:
        data = fx.pdf_bytes()
        doc = self.upload_ok(self.a, self.a_token, self.a_course, ("Lecture 4 — AOP.pdf", data))[0]
        response = self.a.get(f"/api/v1/documents/{doc['id']}/file", headers=self.bearer(self.a_token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, data)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.headers["content-disposition"].startswith("attachment; filename*=UTF-8''"))
        self.assertIn("Lecture%204%20%E2%80%94%20AOP.pdf", response.headers["content-disposition"])
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["cache-control"], "no-store")


class EnvironmentTests(UploadCase):
    def test_g2_upl_11_parser_child_inherits_no_secrets(self) -> None:
        secrets_env = {"INTELLISTUDY_JWT_SECRET": "x" * 40, "INTELLISTUDY_DEEPSEEK_API_KEY": "sk-" + "y" * 30,
                       "DEEPSEEK_API_KEY": "sk-zzz", "AWS_SECRET_ACCESS_KEY": "a", "MY_TOKEN": "t",
                       "DATABASE_URL": "postgresql://u:p@h/db", "HF_TOKEN": "hf_x", "PATH": os.environ["PATH"]}
        env = child_environment(secrets_env)
        self.assertEqual(set(env) & set(secrets_env), {"PATH"})
        work = Path(self.tmp) / "env-probe"
        work.mkdir()
        target = work / "input.pdf"
        target.write_text("env")
        with mock.patch.dict(os.environ, secrets_env):
            run_parse(target, kind="pdf", container="pdf", user_id=self.a_id, course_id=self.a_course,
                      document_id=self.a_course, settings=self.settings, work_root=work / "w", child_module=PROBES)
        names = set(json.loads((work / "input.env.json").read_text()))
        self.assertFalse(names & (set(secrets_env) - {"PATH"}), names)
        self.assertFalse({n for n in names if n.startswith("INTELLISTUDY_")})


class RequestShapeTests(UploadCase):
    def test_g2_upl_14_course_ownership_is_checked_before_any_byte_is_stored(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING"):
            response = self.upload(self.b, self.b_token, self.a_course, ("x.pdf", fx.pdf_bytes()))
        self.assert_same_404(response, self.b_token)
        self.assertEqual(self.incoming_files(), [])
        self.assertEqual(self.documents_count(), 0)

    def test_g2_upl_15_only_file_parts_named_files(self) -> None:
        wrong_field = self.a.post(f"/api/v1/courses/{self.a_course}/documents", headers=self.bearer(self.a_token),
                                  files=[("upload", ("x.pdf", fx.pdf_bytes(), "application/pdf"))])
        self.assertEqual(wrong_field.status_code, 422)
        extra_field = self.a.post(f"/api/v1/courses/{self.a_course}/documents", headers=self.bearer(self.a_token),
                                  data={"owner_id": self.b_id}, files=[("files", ("x.pdf", fx.pdf_bytes(), "application/pdf"))])
        self.assertEqual(extra_field.status_code, 422)
        not_multipart = self.a.post(f"/api/v1/courses/{self.a_course}/documents", headers=self.bearer(self.a_token),
                                    json={"files": "x"})
        self.assertEqual(not_multipart.status_code, 415)
        self.assertEqual(self.incoming_files(), [])
        self.assertEqual(self.documents_count(), 0)

    def test_g2_upl_16_duplicates_only_within_the_same_user_and_course(self) -> None:
        data = fx.pdf_bytes()
        first = self.upload_ok(self.a, self.a_token, self.a_course, ("a.pdf", data))[0]
        again = self.upload_ok(self.a, self.a_token, self.a_course, ("a-copy.pdf", data))[0]
        self.assertEqual((again["id"], again["duplicate"]), (first["id"], True))
        other_course = self.create_course(self.a_token, "Other")
        elsewhere = self.upload_ok(self.a, self.a_token, other_course, ("a.pdf", data))[0]
        self.assertNotEqual(elsewhere["id"], first["id"])
        b_doc = self.upload_ok(self.b, self.b_token, self.b_course, ("a.pdf", data))[0]
        self.assertFalse(b_doc["duplicate"])  # no cross-user "already exists" (ISO-08)
        self.assertNotEqual(b_doc["id"], first["id"])


class UploadRateTests(UploadCase):
    real_rate_limits = True

    def test_g2_upl_17_upload_rate_and_queue_limits(self) -> None:
        for i in range(5):
            self.upload_ok(self.a, self.a_token, self.a_course, (f"d{i}.pdf", fx.pdf_bytes(text=f"distinct {i} " * 30)))
        queue_full = self.upload(self.a, self.a_token, self.a_course, ("d5.pdf", fx.pdf_bytes(text="six " * 30)))
        self.assertEqual(queue_full.status_code, 429)
        self.assertEqual(queue_full.json()["type"], "about:blank#queue_full")
        data = fx.pdf_bytes(text="same " * 30)
        # duplicates create no job (no queue pressure) but still count as uploaded files for the rate limit
        statuses = [self.upload(self.b, self.b_token, self.b_course, ("s.pdf", data)).status_code for _ in range(20)]
        self.assertEqual(statuses, [202] * 20)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            limited = self.upload(self.b, self.b_token, self.b_course, ("s.pdf", data))
        self.assertEqual(limited.status_code, 429)  # file 21 within the hour
        self.assertRegex(limited.headers["retry-after"], r"^\d+$")
        self.assertEqual(self.incoming_files(), [])
        self.clock.advance(3601)  # window over; the old access token has expired too, so sign in again
        fresh = self.login(self.client("10.17.0.9"), "b@example.org")
        self.assertEqual(self.upload(self.b, fresh, self.b_course, ("s.pdf", data)).status_code, 202)


class StorageTests(UploadCase):
    def test_g2_file_01_layout_and_permissions(self) -> None:
        doc = self.upload_ok(self.a, self.a_token, self.a_course, ("a.pdf", fx.pdf_bytes()))[0]
        directory = self.stored_dir(self.a_id, doc["id"])
        stored = directory / "original.pdf"
        self.assertTrue(stored.is_file())
        self.assertEqual(stat.S_IMODE(stored.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(directory.parent.stat().st_mode), 0o700)

    def test_g2_file_02_paths_never_escape_the_root(self) -> None:
        storage = FileStorage(Path(self.tmp) / "s2")
        good = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
        for owner, document in (("..", good), (good, "../x"), (good, good.upper()), ("a/b", good), (good, good + "/..")):
            with self.subTest(owner=owner, document=document), self.assertRaises(StorageError):
                storage.document_dir(owner, document)
        with self.assertRaises(StorageError):
            storage.document_path(good, good, "exe")
        outside = Path(self.tmp) / "outside.part"
        outside.write_bytes(b"x")
        with self.assertRaises(StorageError):
            storage.place(outside, good, good, "pdf")

    def test_g2_file_03_stale_partial_uploads_are_swept(self) -> None:
        storage = self.app.state.storage
        stale = storage.new_incoming()
        fresh = storage.new_incoming()
        old = time.time() - 7200
        os.utime(stale, (old, old))
        self.assertEqual(storage.sweep_incoming(3600), 1)
        self.assertFalse(stale.exists())
        self.assertTrue(fresh.exists())

    def test_g2_file_04_storage_is_not_served_statically(self) -> None:
        doc = self.upload_ok(self.a, self.a_token, self.a_course, ("a.pdf", fx.pdf_bytes()))[0]
        rel = f"{self.a_id}/{doc['id']}/original.pdf"
        for path in (f"/{rel}", f"/storage/{rel}", f"/data/backend/storage/{rel}", f"/api/v1/{rel}", "/.incoming/"):
            with self.subTest(path=path):
                self.assertEqual(self.client().get(path, headers=self.bearer(self.a_token)).status_code, 404)


if __name__ == "__main__":
    import unittest

    unittest.main()

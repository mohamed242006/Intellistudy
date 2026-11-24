"""M4 release gate 2.1 summary ownership isolation (G4-SIS-*), 2.5 summary citation validation (G4-SCV-*) and 2.9
summary storage (G4-CAC-*)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select, update

from backend.app.db.models import Document, Summary
from backend.tests.m4_base import FACTS, M4Case, sentences, sources_of, summary_reply

ZEBRA_TEXT = "Zebra stripes confuse predators in the savanna grasslands. " * 6
QUOKKA_TEXT = "Quokka marsupials smile on Rottnest island near Perth. " * 6


def prompt_text(llm: Any) -> str:
    return "\n".join(m.content for call in llm.calls for m in call)


class SummaryCase(M4Case):
    def setUp(self) -> None:
        super().setUp()
        self.doc_a = self.deck(self.a, self.a_token, self.a_course, "cells.pptx")
        self.llm = self.use(summary_reply)


class SummaryIsolationTests(SummaryCase):
    def test_g4_sis_01_another_user_gets_the_same_404(self) -> None:
        before = self.summary_ok(self.a, self.a_token, self.doc_a)
        calls, jobs = len(self.llm.calls), self.jobs()
        for method in ("get", "post"):
            with self.subTest(method=method), self.assertLogs("intellistudy.security", level="WARNING"):
                response = (self.get_summary if method == "get" else self.post_summary)(self.b, self.b_token,
                                                                                         self.doc_a)
                self.assert_same_404(response, self.b_token)
        self.assertEqual((len(self.llm.calls), self.jobs()), (calls, jobs))
        self.assertEqual(self.get_summary(self.a, self.a_token, self.doc_a).json(), before)

    def test_g4_sis_02_admins_cannot_read_student_summaries(self) -> None:
        self.summary_ok(self.a, self.a_token, self.doc_a)
        for method in ("get", "post"):
            with self.subTest(method=method), self.assertLogs("intellistudy.security", level="WARNING"):
                response = (self.get_summary if method == "get" else self.post_summary)(self.c, self.c_token,
                                                                                         self.doc_a)
                self.assert_same_404(response, self.c_token)

    def test_g4_sis_03_random_and_malformed_ids(self) -> None:
        for raw in (str(uuid.uuid4()), "123", self.doc_a.upper(), "x" * 300):
            for method in ("get", "post"):
                with self.subTest(raw=raw[:12], method=method):
                    response = (self.get_summary if method == "get" else self.post_summary)(self.a, self.a_token, raw)
                    self.assert_same_404(response, self.a_token)

    def test_g4_sis_04_generation_reads_only_this_document_in_scope(self) -> None:
        other = self.doc(self.a, self.a_token, self.a_course, "quokka.pdf", QUOKKA_TEXT)
        self.doc(self.b, self.b_token, self.b_course, "zebra.pdf", ZEBRA_TEXT)
        reads: list[tuple[str, Any]] = []
        store = self.parents
        list_ids, get_many = store.list_ids, store.get_many

        def spy_list(**kw: Any) -> Any:
            reads.append(("list", kw))
            return list_ids(**kw)

        def spy_get(keys: Any, **kw: Any) -> Any:
            reads.append(("get", kw))
            return get_many(keys, **kw)

        store.list_ids = spy_list  # type: ignore[method-assign]
        store.get_many = spy_get  # type: ignore[method-assign]
        self.summary_ok(self.a, self.a_token, self.doc_a)
        self.assertTrue(reads)
        for kind, kwargs in reads:
            if kind == "list":
                self.assertEqual(kwargs, {"document_uid": self.doc_a})
            else:
                self.assertEqual(kwargs, {"user_id": self.a_id, "course_id": self.a_course})
        text = prompt_text(self.llm)
        self.assertIn("Mitochondria", text)
        for foreign in ("Quokka", "Zebra"):
            self.assertNotIn(foreign, text)
        self.assertNotIn(other, text)

    def test_g4_sis_05_identical_uploads_never_share_a_summary(self) -> None:
        doc_b = self.deck(self.b, self.b_token, self.b_course, "cells.pptx")
        a = self.summary_ok(self.a, self.a_token, self.doc_a)
        calls = len(self.llm.calls)
        b = self.summary_ok(self.b, self.b_token, doc_b)
        self.assertGreater(len(self.llm.calls), calls)  # generated again for B, not reused
        self.assertEqual((a["document_id"], b["document_id"]), (self.doc_a, doc_b))
        self.assertEqual({c["document_id"] for c in b["citations"]}, {doc_b})
        with self.db() as session:
            rows = list(session.scalars(select(Summary)))
        self.assertEqual(sorted((r.owner_id, r.document_id) for r in rows),
                         sorted([(self.a_id, self.doc_a), (self.b_id, doc_b)]))

    def test_g4_sis_06_non_ready_documents_are_refused(self) -> None:
        calls, jobs = len(self.llm.calls), self.jobs()
        for status in ("queued", "extracting", "embedding", "indexing", "failed"):
            with self.subTest(status=status):
                self._status(status)
                response = self.post_summary(self.a, self.a_token, self.doc_a)
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(response.json()["type"], "about:blank#document_not_ready")
        self._status("deleting")
        self.assert_same_404(self.post_summary(self.a, self.a_token, self.doc_a), self.a_token)
        self.assertEqual((len(self.llm.calls), self.jobs()), (calls, jobs))

    def _status(self, status: str) -> None:
        with self.db() as session:
            session.execute(update(Document).where(Document.id == self.doc_a).values(status=status))
            session.commit()

    def test_g4_sis_07_scope_fields_in_the_body_are_rejected(self) -> None:
        for field in ("owner_id", "user_id", "course_id", "document_id", "filters"):
            with self.subTest(field=field):
                response = self.a.post(f"/api/v1/documents/{self.doc_a}/summary", json={field: self.b_id},
                                       headers=self.bearer(self.a_token))
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.jobs(), 0)

    def test_g4_sis_08_foreign_parents_from_the_store_are_dropped(self) -> None:
        doc_b = self.doc(self.b, self.b_token, self.b_course, "zebra.pdf", ZEBRA_TEXT)
        b_keys = sorted(self.parents.list_ids(document_uid=doc_b))
        foreign = self.parents.get_many(b_keys, user_id=self.b_id, course_id=self.b_course)
        get_many = self.parents.get_many

        def leaky(keys: Any, **kwargs: Any) -> Any:
            return {**get_many(keys, **kwargs), **foreign}  # a corrupted store returns B's sections too

        self.parents.get_many = leaky  # type: ignore[method-assign]
        with self.assertLogs("intellistudy.security", level="ERROR") as logs:
            summary = self.summary_ok(self.a, self.a_token, self.doc_a)
        self.assertIn("source_scope_violation", [getattr(r, "security_event", {}).get("event") for r in logs.records])
        self.assertTrue(any(r.levelno == logging.ERROR for r in logs.records))
        self.assertNotIn("Zebra", prompt_text(self.llm))
        self.assertNotIn("Zebra", str(summary))


class SummaryCitationTests(SummaryCase):
    def settings_overrides(self) -> dict[str, Any]:
        return {**super().settings_overrides(), "summary_batch_tokens": 200}

    def stored_passages(self, document_id: str) -> set[str]:
        keys = sorted(self.parents.list_ids(document_uid=document_id))
        return {p.text for p in self.parents.get_many(keys, user_id=self.a_id, course_id=self.a_course).values()}

    def test_g4_scv_01_uncited_material_is_removed(self) -> None:
        self.use(lambda messages: (
            "Here is a summary of the material.\n### [S1]\nMitochondria produce cellular energy through oxidative "
            "phosphorylation [S1]. Ribosomes assemble proteins from messenger templates.\n### [S2]\n"
            "Photosynthesis converts sunlight into chemical energy inside chloroplasts."))
        summary = self.summary_ok(self.a, self.a_token, self.doc_a)
        text = " ".join(s["text"] for s in summary["sections"])
        self.assertIn("Mitochondria produce cellular energy", text)
        for removed in ("Ribosomes assemble", "Photosynthesis converts", "Here is a summary"):
            self.assertNotIn(removed, text)
        self.assertTrue(all(s["citations"] for s in summary["sections"]))
        other = self.deck(self.a, self.a_token, self.a_course, "uncited.pptx", ["Uncited slide about comets. " * 3])
        self.use(["Comets are icy bodies.\nThey orbit the sun."])
        self.assertEqual(self.post_summary(self.a, self.a_token, other).status_code, 202)
        self.generate()
        failed = self.get_summary(self.a, self.a_token, other).json()
        self.assertEqual((failed["status"], failed["error_code"], failed["sections"]), ("failed", "ungrounded", []))

    def test_g4_scv_02_invented_tags_never_become_citations(self) -> None:
        self.use(lambda messages: "### [S1]\nMitochondria produce cellular energy through oxidative phosphorylation "
                                  "[S1][S9].")
        summary = self.summary_ok(self.a, self.a_token, self.doc_a)
        self.assertEqual([c["number"] for c in summary["citations"]], [1])
        self.assertTrue(any("S9" in w for w in summary["warnings"]))
        supplied = self.stored_passages(self.doc_a)
        for citation in summary["citations"]:
            self.assertEqual(citation["document_id"], self.doc_a)
            self.assertIn(citation["passage"], supplied)

    def test_g4_scv_03_passages_and_ranges_come_from_the_store(self) -> None:
        self.use(lambda messages: "\n".join(  # the model claims a location; ranges must ignore it
            f"### [{tag}] (pages 90 to 99)\n{sentences(text)[0].rstrip('.')} [{tag}]."
            for tag, text in sources_of(messages)))
        summary = self.summary_ok(self.a, self.a_token, self.doc_a)
        supplied = self.stored_passages(self.doc_a)
        by_number = {c["number"]: c for c in summary["citations"]}
        self.assertTrue(summary["sections"])
        for section in summary["sections"]:
            cited = [by_number[n] for n in section["citations"]]
            slides = [c["slide"] for c in cited]
            self.assertEqual(section["source_range"], {"kind": "slide", "start": min(slides), "end": max(slides)})
            self.assertNotEqual(section["source_range"]["end"], 99)
        for citation in summary["citations"]:
            self.assertIn(citation["passage"], supplied)

    def test_g4_scv_04_unsupported_sentences_are_removed_and_counted(self) -> None:
        self.use(lambda messages: (
            "### [S1]\nMitochondria produce cellular energy through oxidative phosphorylation [S1]. "
            "Mitochondria produce 4200 kilojoules of energy every second [S1]. "
            "Penguins migrate across Antarctic glaciers during winter storms [S1]. "
            "Ribosomes are described as \"tiny protein factories everywhere\" [S1]."))
        summary = self.summary_ok(self.a, self.a_token, self.doc_a)
        text = " ".join(s["text"] for s in summary["sections"])
        for removed in ("4200", "Penguins", "tiny protein factories"):
            self.assertNotIn(removed, text)
        self.assertGreaterEqual(summary["grounding"]["removed"], 3)
        self.assertIn("Mitochondria produce cellular energy", text)

    def test_g4_scv_05_map_batches_cover_every_section_exactly_once(self) -> None:
        texts = [f"{fact} {fact}" for fact in FACTS]
        doc = self.deck(self.a, self.a_token, self.a_course, "long.pptx", texts)
        self.doc(self.a, self.a_token, self.a_course, "quokka.pdf", QUOKKA_TEXT)
        self.llm = self.use(summary_reply)
        summary = self.summary_ok(self.a, self.a_token, doc)
        self.assertGreaterEqual(len(self.llm.calls), 2)  # several map calls
        seen = [text for call in self.llm.calls for _, text in sources_of(call)]
        stored = self.stored_passages(doc)
        self.assertEqual(sorted(seen), sorted(stored))  # every section once, nothing else
        self.assertEqual(len(seen), len(set(seen)))
        self.assertNotIn("Quokka", prompt_text(self.llm))
        self.assertEqual(summary["chunk_count"], len(stored))

    def test_g4_scv_06_images_removed_and_html_returned_as_data(self) -> None:
        self.use(lambda messages: (
            "### [S1]\nMitochondria produce cellular energy ![x](https://evil.example/c?d=1) through oxidative "
            "phosphorylation <img src=https://evil.example/p.png> <script>alert(1)</script> [S1]."))
        self.post_summary(self.a, self.a_token, self.doc_a)
        self.generate()
        response = self.get_summary(self.a, self.a_token, self.doc_a)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        text = " ".join(s["text"] for s in response.json()["sections"])
        self.assertNotIn("](https://evil.example", text)
        self.assertNotIn("<img", text.lower())

    def test_g4_scv_07_stored_summary_reads_back_identically(self) -> None:
        first = self.summary_ok(self.a, self.a_token, self.doc_a)
        again = self.post_summary(self.a, self.a_token, self.doc_a)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json(), first)
        self.assertEqual(self.get_summary(self.a, self.a_token, self.doc_a).json(), first)
        with self.db() as session:
            row = session.scalars(select(Summary).where(Summary.document_id == self.doc_a)).one()
        self.assertEqual((row.sections, row.citations, row.warnings), (first["sections"], first["citations"],
                                                                       first["warnings"]))


class SummaryStorageTests(SummaryCase):
    real_rate_limits = True

    def test_g4_cac_01_stored_summary_is_served_without_generation(self) -> None:
        first = self.post_summary(self.a, self.a_token, self.doc_a)
        self.assertEqual(first.status_code, 202)
        self.generate()
        calls, jobs, used = len(self.llm.calls), self.jobs(), self.usage(self.a_id)
        for _ in range(15):  # beyond the 10/hour generation limit: stored reads never count
            self.assertEqual(self.post_summary(self.a, self.a_token, self.doc_a).status_code, 200)
            self.assertEqual(self.get_summary(self.a, self.a_token, self.doc_a).status_code, 200)
        self.assertEqual((len(self.llm.calls), self.jobs(), self.usage(self.a_id)), (calls, jobs, used))
        self.assertEqual(self.generate(), 0)

    def test_g4_cac_02_concurrent_requests_share_one_generation(self) -> None:
        views = [self.post_summary(self.a, self.a_token, self.doc_a) for _ in range(4)]
        self.assertEqual({v.status_code for v in views}, {202})
        self.assertEqual({(v.json()["status"], v.json()["pending"]) for v in views}, {("generating", True)})
        self.assertEqual(self.jobs(), 1)
        self.generate()
        self.assertEqual(len(self.llm.calls), 1)

    def test_g4_cac_03_regeneration_replaces_atomically_and_failure_keeps_the_old(self) -> None:
        old = self.summary_ok(self.a, self.a_token, self.doc_a)
        self.use(lambda messages: "### [S2]\nPhotosynthesis converts sunlight into chemical energy inside chloroplasts "
                                  "[S2].")
        self.assertEqual(self.post_summary(self.a, self.a_token, self.doc_a, regenerate=True).status_code, 202)
        during = self.get_summary(self.a, self.a_token, self.doc_a).json()
        self.assertEqual((during["status"], during["pending"], during["sections"]), ("ready", True, old["sections"]))
        self.generate()
        new = self.get_summary(self.a, self.a_token, self.doc_a).json()
        self.assertIn("Photosynthesis", new["sections"][0]["text"])
        self.use(["__error__"])
        with self.assertLogs(level="WARNING"):
            self.post_summary(self.a, self.a_token, self.doc_a, regenerate=True)
            self.generate()
        kept = self.get_summary(self.a, self.a_token, self.doc_a).json()
        self.assertEqual((kept["status"], kept["error_code"], kept["sections"]),
                         ("ready", "llm_unavailable", new["sections"]))

    def test_g4_cac_04_metadata_is_stored_and_owned(self) -> None:
        summary = self.summary_ok(self.a, self.a_token, self.doc_a)
        self.assertEqual(summary["model"], "scripted")
        self.assertTrue(summary["generated_at"])
        self.assertEqual(summary["chunk_count"], len(FACTS))
        self.assertEqual(set(summary["grounding"]), {"checked", "supported", "removed"})
        with self.db() as session:
            row = session.scalars(select(Summary).where(Summary.document_id == self.doc_a)).one()
        self.assertEqual((row.owner_id, row.course_id), (self.a_id, self.a_course))


if __name__ == "__main__":
    import unittest

    unittest.main()

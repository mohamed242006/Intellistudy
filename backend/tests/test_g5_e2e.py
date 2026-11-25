"""M5 gate 2.9: the end-to-end vertical slice, driven through the HTTP API only.

Fresh users run the whole flow in lockstep (every step for every user before the next step). Model replies are scripted
from the prompt (chat answers cite their first source, summaries and quizzes as in M4); no network call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text, update

from backend.app.db.base import Base
from backend.app.db.models import LlmUsage, ProcessingJob
from backend.app.main import create_app
from backend.tests.m1_base import CSRF, PASSWORD, NoLimiter, _quiet_json_handler
from backend.tests.m4_base import (
    FACTS,
    M4Case,
    QuizModel,
    pdf_pages,
    pptx_slides,
    sentences,
    sources_of,
    summary_reply,
)
from backend.tests.m5_base import varied

SHARED_PDF = pdf_pages([FACTS[0], FACTS[1]])  # the same bytes for both users (G5-E2E-02)
OWN_SLIDES = {
    "a": [FACTS[2], FACTS[3]],
    "b": ["Glaciers carve valleys through slow mechanical erosion. Moraines mark the furthest advance of ice sheets. "
          "Meltwater streams deposit sorted gravel downstream.",
          "Volcanoes vent molten rock through crustal fissures. Basalt cools quickly into fine grained stone. "
          "Calderas form after magma chambers collapse."],
}
OWN_WORDS = {"a": ("Neurons", "Synapses", "Enzymes"), "b": ("Glaciers", "Moraines", "Volcanoes")}


def chat_reply(messages: Any) -> str:
    tag, body = sources_of(messages)[0]
    first = next(iter(sentences(body)), body.strip().split("\n")[0])
    return f"{first.rstrip('.')} [{tag}]."


@dataclass
class Student:
    name: str
    email: str
    client: Any
    token: str = ""
    user_id: str = ""
    course: str = ""
    documents: list[str] = field(default_factory=list)
    conversation: str = ""
    quiz: str = ""
    attempts: list[str] = field(default_factory=list)
    bodies: list[str] = field(default_factory=list)

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


class E2ECase(M4Case):
    with_users = False

    def setUp(self) -> None:
        super().setUp()
        self.quizzes = QuizModel(correct_at=None, transform=varied())
        self.use(self.reply)

    def reply(self, messages: Any) -> str:
        system = messages[0].content
        if "study summary" in system:
            return summary_reply(messages)
        if "practice questions" in system:
            return str(self.quizzes(messages))
        return chat_reply(messages)

    # ------------------------------------------------------------------------------------------------ steps
    def expect(self, student: Student, response: Any, status: int) -> dict[str, Any]:
        self.assertEqual(response.status_code, status, f"{student.name}: {response.text}")
        student.bodies.append(response.text)
        return dict(response.json()) if response.content else {}

    def flow(self, students: list[Student], *, until: str = "end") -> None:
        """The documented flow, in lockstep. ``until`` stops after a named step (used by later tests)."""
        for s in students:
            self.expect(s, s.client.post("/api/v1/auth/register", json={"email": s.email, "name": s.name,
                                                                        "password": PASSWORD}), 201)
        for s in students:
            body = self.expect(s, s.client.post("/api/v1/auth/login", json={"email": s.email, "password": PASSWORD}),
                               200)
            s.token = body["access_token"]
            s.user_id = self.expect(s, s.client.get("/api/v1/auth/me", headers=s.headers()), 200)["id"]
        for s in students:
            s.course = self.expect(s, s.client.post("/api/v1/courses", json={"name": f"{s.name} biology"},
                                                    headers=s.headers()), 201)["id"]
        for s in students:
            files = [("files", ("shared.pdf", SHARED_PDF, "application/pdf")),
                     ("files", ("own.pptx", pptx_slides(OWN_SLIDES[s.name]),
                                "application/vnd.openxmlformats-officedocument.presentationml.presentation"))]
            uploaded = self.expect(s, s.client.post(f"/api/v1/courses/{s.course}/documents", files=files,
                                                    headers=s.headers()), 202)
            s.documents = [d["id"] for d in uploaded["documents"]]
        if until == "uploaded":
            return
        self.process()
        for s in students:
            listed = self.expect(s, s.client.get(f"/api/v1/courses/{s.course}/documents", headers=s.headers()), 200)
            self.assertEqual({d["status"] for d in listed["items"]}, {"ready"})
        for s in students:
            s.conversation = self.expect(s, s.client.post(f"/api/v1/courses/{s.course}/conversations", json={},
                                                          headers=s.headers()), 201)["id"]
            answer = self.expect(s, s.client.post(f"/api/v1/conversations/{s.conversation}/messages",
                                                  json={"question": "What do mitochondria produce?"},
                                                  headers=s.headers()), 201)
            self.assertTrue(answer["citations"])
            self.assertLessEqual({c["document_id"] for c in answer["citations"]}, set(s.documents))
        for s in students:
            self.expect(s, s.client.post(f"/api/v1/documents/{s.documents[0]}/summary", json={},
                                         headers=s.headers()), 202)
            s.quiz = self.expect(s, s.client.post(f"/api/v1/courses/{s.course}/quizzes", json={"question_count": 8},
                                                  headers=s.headers()), 202)["id"]
        self.generate()
        for s in students:
            summary = self.expect(s, s.client.get(f"/api/v1/documents/{s.documents[0]}/summary",
                                                  headers=s.headers()), 200)
            self.assertEqual(summary["status"], "ready")
            self.assertLessEqual({c["document_id"] for c in summary["citations"]}, set(s.documents))
            quiz = self.expect(s, s.client.get(f"/api/v1/quizzes/{s.quiz}", headers=s.headers()), 200)
            self.assertEqual((quiz["status"], len(quiz["questions"])), ("ready", 8))
        if until == "quiz":
            return
        for s in students:
            attempt = self.expect(s, s.client.post(f"/api/v1/quizzes/{s.quiz}/attempts", headers=s.headers()), 201)
            s.attempts.append(attempt["id"])
            for question in attempt["questions"]:  # a student guessing: first option, "true"
                body = {"choice": 0} if question["type"] == "mcq" else {"value": True}
                self.expect(s, s.client.put(f"/api/v1/attempts/{attempt['id']}/answers/{question['id']}", json=body,
                                            headers=s.headers()), 200)
        if until == "answered":
            return
        for s in students:
            results = self.expect(s, s.client.post(f"/api/v1/attempts/{s.attempts[0]}/submit", headers=s.headers()),
                                  200)
            self.assertEqual(self.expect(s, s.client.get(f"/api/v1/attempts/{s.attempts[0]}/results",
                                                         headers=s.headers()), 200), results)
            missed = [q for q in results["questions"] if not q["correct"]]
            self.assertTrue(missed)
            self.assertLessEqual({q["citation"]["document_id"] for q in results["questions"]}, set(s.documents))
            retry = self.expect(s, s.client.post(f"/api/v1/attempts/{s.attempts[0]}/retry-missed",
                                                 headers=s.headers()), 201)
            s.attempts.append(retry["id"])
            correct = {q["question_id"]: q["correct_answer"] for q in missed}
            for question in retry["questions"]:  # learned from the results: answer correctly now
                answer = {k: v for k, v in correct[question["id"]].items() if v is not None}
                self.expect(s, s.client.put(f"/api/v1/attempts/{retry['id']}/answers/{question['id']}", json=answer,
                                            headers=s.headers()), 200)
            again = self.expect(s, s.client.post(f"/api/v1/attempts/{retry['id']}/submit", headers=s.headers()), 200)
            self.assertEqual(again["score"], again["max_score"])
        if until == "retried":
            return
        for s in students:
            s.token = self.expect(s, s.client.post("/api/v1/auth/refresh", headers=CSRF), 200)["access_token"]
            self.expect(s, s.client.get("/api/v1/auth/me", headers=s.headers()), 200)
            self.assertEqual(s.client.post("/api/v1/auth/logout", headers=CSRF).status_code, 204)
            self.assertEqual(s.client.post("/api/v1/auth/refresh", headers=CSRF).status_code, 401)

    def student(self, name: str, ip: str) -> Student:
        return Student(name=name, email=f"{name}.e2e@example.org", client=self.client(ip))


class EndToEndTests(E2ECase):
    def test_g5_e2e_01_the_whole_flow_for_one_student(self) -> None:
        a = self.student("a", "10.2.0.1")
        self.flow([a])
        self.assertEqual(len(a.attempts), 2)

    def test_g5_e2e_02_two_students_with_the_same_file_never_see_each_other(self) -> None:
        a, b = self.student("a", "10.2.0.1"), self.student("b", "10.2.0.2")
        self.flow([a, b])
        for me, other in ((a, b), (b, a)):
            secrets = [other.user_id, other.course, other.conversation, other.quiz, *other.documents, *other.attempts,
                       *OWN_WORDS[other.name]]
            seen = "\n".join(me.bodies)
            with self.subTest(student=me.name):
                self.assertEqual([x for x in secrets if x in seen], [])

    def test_g5_e2e_03_deleting_a_document_then_the_course_leaves_nothing(self) -> None:
        a, b = self.student("a", "10.2.0.1"), self.student("b", "10.2.0.2")
        self.flow([a, b], until="retried")
        pdf = a.documents[0]
        self.assertEqual(a.client.delete(f"/api/v1/documents/{pdf}", headers=a.headers()).status_code, 204)
        self.assertEqual(a.client.get(f"/api/v1/documents/{pdf}/summary", headers=a.headers()).status_code, 404)
        quiz = a.client.get(f"/api/v1/quizzes/{a.quiz}", headers=a.headers()).json()
        self.assertEqual((quiz["status"], quiz["questions"]), ("invalid", []))  # T-3: it used both documents
        for attempt in a.attempts:
            self.assertEqual(a.client.get(f"/api/v1/attempts/{attempt}", headers=a.headers()).status_code, 404)
        self.assertEqual(a.client.delete(f"/api/v1/courses/{a.course}", headers=a.headers()).status_code, 204)
        with self.db() as session:
            for table in Base.metadata.sorted_tables:
                if "owner_id" in table.c and table.name != "llm_usage":
                    count = session.scalar(select(func.count()).select_from(table).where(
                        table.c.owner_id == a.user_id))
                    with self.subTest(table=table.name):
                        self.assertEqual(count, 0)
            self.assertGreater(session.scalar(select(func.count()).select_from(LlmUsage).where(
                LlmUsage.owner_id == a.user_id)) or 0, 0)  # the ledger keeps A's usage (UPL-16)
        for document in a.documents:
            self.assertEqual(self.vector_records(document), [])
            self.assertEqual(self.parent_keys(document), set())
            self.assertFalse(self.stored_dir(a.user_id, document).exists())
        self.assertFalse((Path(self.settings.storage_root).resolve() / a.user_id).exists()
                         and any((Path(self.settings.storage_root).resolve() / a.user_id).iterdir()))
        for url in (f"/api/v1/quizzes/{b.quiz}", f"/api/v1/attempts/{b.attempts[0]}/results",
                    f"/api/v1/documents/{b.documents[0]}/summary"):
            self.assertEqual(b.client.get(url, headers=b.headers()).status_code, 200, url)
        self.assertTrue(self.vector_records(b.documents[0]))

    def test_g5_e2e_04_a_restart_mid_flow_recovers_jobs_and_attempts(self) -> None:
        a = self.student("a", "10.2.0.1")
        self.flow([a], until="answered")
        attempt = a.client.get(f"/api/v1/attempts/{a.attempts[0]}", headers=a.headers()).json()
        late = self.expect(a, a.client.post(f"/api/v1/courses/{a.course}/documents", headers=a.headers(), files=[
            ("files", ("late.pdf", pdf_pages([FACTS[3]]), "application/pdf"))]), 202)["documents"][0]["id"]
        quiz = self.expect(a, a.client.post(f"/api/v1/courses/{a.course}/quizzes", headers=a.headers(),
                                            json={"question_count": 5, "document_ids": [a.documents[0]]}), 202)["id"]
        with self.db() as session:  # the crash: both jobs were mid-run
            session.execute(update(ProcessingJob).where(ProcessingJob.document_id == late).values(status="running"))
            session.execute(text("UPDATE generation_jobs SET status = 'running' WHERE quiz_id = :q"), {"q": quiz})
            session.commit()
        restarted = create_app(self.settings, rate_limiter=NoLimiter(), clock=self.clock, ai=self.app.state.ai)
        _quiet_json_handler()
        self.app = restarted
        self.assertEqual((restarted.state.jobs.recover(), restarted.state.generation_runner.recover()), (1, 1))
        self.process()
        self.generate()
        client = self.client("10.2.0.9")
        self.assertEqual(client.get(f"/api/v1/documents/{late}", headers=a.headers()).json()["status"], "ready")
        self.assertEqual(client.get(f"/api/v1/quizzes/{quiz}", headers=a.headers()).json()["status"], "ready")
        resumed = client.post(f"/api/v1/quizzes/{a.quiz}/attempts", headers=a.headers())
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual((resumed.json()["id"], resumed.json()["answers"]), (attempt["id"], attempt["answers"]))
        self.assertEqual(client.post(f"/api/v1/attempts/{attempt['id']}/submit", headers=a.headers()).status_code, 200)

    def test_g5_e2e_05_without_a_model_provider_quiz_taking_still_works(self) -> None:
        a = self.student("a", "10.2.0.1")
        self.flow([a], until="quiz")
        self.app.state.ai._provider = None
        chat = self.expect(a, a.client.post(f"/api/v1/conversations/{a.conversation}/messages",
                                            json={"question": "What do mitochondria produce?"}, headers=a.headers()), 201)
        self.assertEqual((chat["state"], chat["refusal_reason"]), ("refused", "llm_unavailable"))  # M3 G3-ST-02
        unavailable = [
            a.client.post(f"/api/v1/documents/{a.documents[1]}/summary", json={}, headers=a.headers()),
            a.client.post(f"/api/v1/courses/{a.course}/quizzes", json={"question_count": 5}, headers=a.headers()),
        ]
        for response in unavailable:
            with self.subTest(url=str(response.url)):
                self.assertEqual((response.status_code, response.json()["type"]), (503, "about:blank#llm_unavailable"))
        self.assertEqual(a.client.get(f"/api/v1/documents/{a.documents[0]}/summary", headers=a.headers()).status_code,
                         200)
        attempt = self.expect(a, a.client.post(f"/api/v1/quizzes/{a.quiz}/attempts", headers=a.headers()), 201)
        for question in attempt["questions"]:
            body = {"choice": 1} if question["type"] == "mcq" else {"value": False}
            self.expect(a, a.client.put(f"/api/v1/attempts/{attempt['id']}/answers/{question['id']}", json=body,
                                        headers=a.headers()), 200)
        results = self.expect(a, a.client.post(f"/api/v1/attempts/{attempt['id']}/submit", headers=a.headers()), 200)
        self.assertEqual(results["max_score"], 8)
        self.assertEqual(json.loads(a.bodies[-1])["attempt_id"], attempt["id"])

"""M4 release gate 2.2 quiz ownership isolation (G4-QIS-*), 2.6 quiz answer validation (G4-QAV-*) and 2.7 no
answer-key leakage (G4-KEY-*)."""

from __future__ import annotations

import ast
import json
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from ai.answering.llm import ScriptedLLM
from backend.app.db.models import Document, GenerationJob, LlmUsage, Quiz, QuizAnswerKey
from backend.app.services import quizgen
from backend.app.services.sources import Section
from backend.tests.m4_base import FACTS, M4Case, QuizModel, mcq, true_false

ROOT = Path(__file__).resolve().parents[2]
SENTENCE = "Mitochondria produce cellular energy through oxidative phosphorylation."
SECTION = Section(key="d1:c1", document_id="d1", file_name="cells.pptx", citation_label="slide 1", page=None, slide=1,
                  heading="Topic 1", text=FACTS[0], tokens=60)
BY_TAG = {"S1": SECTION}
KEY_NAME = re.compile(r"^(correct.*|answer.*|rationale.*|evidence.*|is_correct)$")
PUBLIC_QUESTION = {"id", "position", "type", "stem", "options", "topic", "difficulty", "cognitive_level"}


def check(item: Any, types: tuple[str, ...] = ("mcq", "true_false")) -> str:
    candidate, reason = quizgen.validate(item, BY_TAG, types)
    return "ok" if candidate is not None else reason


def walk_keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from walk_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from walk_keys(inner)


def tf_distinct(item: dict[str, Any]) -> dict[str, Any]:
    """True/false stems that are not the evidence string itself (so a leak of the evidence is detectable)."""
    if item["type"] == "true_false":
        words = item["stem"].rstrip(".").split()
        item = {**item, "stem": " ".join(words[:-1]) + "."}
    return item


class QuizCase(M4Case):
    def setUp(self) -> None:
        super().setUp()
        self.doc_a = self.deck(self.a, self.a_token, self.a_course, "cells.pptx")
        self.model = QuizModel()
        self.llm = self.use(self.model)


class QuizIsolationTests(QuizCase):
    def test_g4_qis_01_another_users_course(self) -> None:
        for method in ("post", "get"):
            with self.subTest(method=method), self.assertLogs("intellistudy.security", level="WARNING"):
                response = (self.post_quiz(self.b, self.b_token, self.a_course, question_count=5) if method == "post"
                            else self.b.get(f"/api/v1/courses/{self.a_course}/quizzes", headers=self.bearer(self.b_token)))
                self.assert_same_404(response, self.b_token)
        self.assertEqual(self.jobs(), 0)

    def test_g4_qis_02_another_user_or_admin_on_a_quiz(self) -> None:
        quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5)
        keys = len(self.keys(quiz["id"]))
        for client, token in ((self.b, self.b_token), (self.c, self.c_token)):
            for method, path in (("GET", f"/api/v1/quizzes/{quiz['id']}"), ("DELETE", f"/api/v1/quizzes/{quiz['id']}"),
                                 ("POST", f"/api/v1/quizzes/{quiz['id']}/regenerate")):
                with self.subTest(token=token[-6:], method=method), \
                        self.assertLogs("intellistudy.security", level="WARNING"):
                    self.assert_same_404(client.request(method, path, headers=self.bearer(token)), token)
        self.assertEqual(self.get_quiz(self.a, self.a_token, quiz["id"]).json(), quiz)
        self.assertEqual(len(self.keys(quiz["id"])), keys)

    def test_g4_qis_03_document_selection_outside_the_scope(self) -> None:
        b_ready = self.deck(self.b, self.b_token, self.b_course, "b.pptx")
        b_waiting = self.deck(self.b, self.b_token, self.b_course, "waiting.pptx", ["Waiting slide about comets. " * 3])
        with self.db() as session:
            session.execute(update(Document).where(Document.id == b_waiting).values(status="indexing"))
            session.commit()
        other_course = self.create_course(self.b_token, "Other course")
        b_other = self.deck(self.b, self.b_token, other_course, "other.pptx")
        for name, ids in (("foreign", [self.doc_a]), ("not-ready", [b_waiting]), ("other-course", [b_other]),
                          ("malformed", ["not-an-id"])):
            with self.subTest(case=name), self.assertLogs("intellistudy.security", level="WARNING"):
                response = self.post_quiz(self.b, self.b_token, self.b_course, document_ids=ids, question_count=5)
                self.assert_same_404(response, self.b_token)
        self.assertEqual(self.jobs(), 0)
        ok = self.post_quiz(self.b, self.b_token, self.b_course, document_ids=[b_ready], question_count=5)
        self.assertEqual((ok.status_code, ok.json()["source_document_ids"]), (202, [b_ready]))

    def test_g4_qis_04_generation_reads_only_the_quiz_sources(self) -> None:
        second = self.deck(self.a, self.a_token, self.a_course, "nerves.pptx", [FACTS[2], FACTS[3]])
        self.doc(self.a, self.a_token, self.a_course, "quokka.pdf", "Quokka marsupials smile on Rottnest island. " * 6)
        self.doc(self.b, self.b_token, self.b_course, "zebra.pdf", "Zebra stripes confuse predators daily. " * 6)
        reads: list[dict[str, Any]] = []
        get_many = self.parents.get_many

        def spy(keys: Any, **kw: Any) -> Any:
            reads.append(kw)
            return get_many(keys, **kw)

        self.parents.get_many = spy  # type: ignore[method-assign]
        quiz = self.quiz_ok(self.a, self.a_token, self.a_course, document_ids=[self.doc_a, second], question_count=5)
        self.assertEqual(quiz["status"], "ready")
        self.assertTrue(reads)
        self.assertTrue(all(kw == {"user_id": self.a_id, "course_id": self.a_course} for kw in reads))
        prompts = "\n".join(m.content for call in self.llm.calls for m in call)
        self.assertNotIn("Quokka", prompts)
        self.assertNotIn("Zebra", prompts)
        for key in self.keys(quiz["id"]):
            self.assertTrue(set(key.source_document_ids) <= {self.doc_a, second})
            self.assertTrue(all(k.split(":")[0] in {self.doc_a, second} for k in key.source_chunk_ids))

    def test_g4_qis_05_random_and_malformed_quiz_ids(self) -> None:
        for raw in (str(uuid.uuid4()), "123", "x" * 300):
            for method, path in (("GET", f"/api/v1/quizzes/{raw}"), ("DELETE", f"/api/v1/quizzes/{raw}"),
                                 ("POST", f"/api/v1/quizzes/{raw}/regenerate")):
                with self.subTest(raw=raw[:8], method=method):
                    self.assert_same_404(self.a.request(method, path, headers=self.bearer(self.a_token)),
                                         self.a_token)

    def test_g4_qis_06_scope_fields_and_oversized_selections_are_rejected(self) -> None:
        for field in ("owner_id", "user_id", "course_id", "filters", "answer_key"):
            with self.subTest(field=field):
                response = self.a.post(f"/api/v1/courses/{self.a_course}/quizzes",
                                       json={"question_count": 5, field: "x"}, headers=self.bearer(self.a_token))
                self.assertEqual(response.status_code, 422, response.text)
        many = [str(uuid.uuid4()) for _ in range(21)]
        self.assertEqual(self.post_quiz(self.a, self.a_token, self.a_course, document_ids=many,
                                        question_count=5).status_code, 422)
        self.assertEqual(self.jobs(), 0)

    def test_g4_qis_07_lists_show_only_the_owners_quizzes_of_that_course(self) -> None:
        mine = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5)["id"]
        course2 = self.create_course(self.a_token, "Second course")
        self.deck(self.a, self.a_token, course2, "c2.pptx")
        self.quiz_ok(self.a, self.a_token, course2, question_count=5)
        self.deck(self.b, self.b_token, self.b_course, "b.pptx")
        self.quiz_ok(self.b, self.b_token, self.b_course, question_count=5)
        listed = self.a.get(f"/api/v1/courses/{self.a_course}/quizzes", headers=self.bearer(self.a_token)).json()
        self.assertEqual([q["id"] for q in listed["items"]], [mine])


class QuizValidationTests(QuizCase):
    def test_g4_qav_01_malformed_questions_are_dropped(self) -> None:
        good = mcq("S1", SENTENCE)
        self.assertEqual(check(good), "ok")
        broken = {
            "3 options": {**good, "options": good["options"][:3]},
            "5 options": {**good, "options": [*good["options"], "Extra choice here"]},
            "duplicate": {**good, "options": [good["options"][0]] * 2 + good["options"][2:]},
            "empty": {**good, "options": ["", *good["options"][1:]]},
            "index none": {**good, "correct_index": None}, "index -1": {**good, "correct_index": -1},
            "index 4": {**good, "correct_index": 4}, "index bool": {**good, "correct_index": True},
            "index str": {**good, "correct_index": "0"},
            "tf string": {**true_false("S1", SENTENCE), "answer": "true"},
            "tf int": {**true_false("S1", SENTENCE), "answer": 1},
            "tf missing": {k: v for k, v in true_false("S1", SENTENCE).items() if k != "answer"},
            "extra field": {**good, "hint": "the first one"},
        }
        for name, item in broken.items():
            with self.subTest(case=name):
                self.assertNotEqual(check(item), "ok")
        self.use(QuizModel(transform=lambda q: {**q, "options": q["options"][:3]} if q["type"] == "mcq" else q))
        quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5)
        self.assertEqual({q["type"] for q in quiz["questions"]}, {"true_false"})  # every malformed MCQ dropped

    def test_g4_qav_02_evidence_must_be_quoted_from_a_supplied_source(self) -> None:
        good = mcq("S1", SENTENCE)
        self.assertEqual(check({**good, "sources": ["S9"]}), "evidence")
        self.assertEqual(check({**good, "evidence": "Mitochondria produce cellular energy by fermentation only."}),
                         "evidence")
        self.assertEqual(check({**good, "evidence": "  mitochondria PRODUCE cellular\nenergy through oxidative "
                                                     "phosphorylation."}), "ok")  # whitespace and case only

    def test_g4_qav_03_the_correct_answer_must_be_supported(self) -> None:
        good = mcq("S1", SENTENCE)
        unsupported = {**good, "options": ["Nuclear fusion reactors", *good["options"][1:]]}
        self.assertEqual(check(unsupported), "unsupported_answer")
        tf = {**true_false("S1", SENTENCE), "stem": "Volcanic eruptions reshape distant coastlines every year."}
        self.assertEqual(check(tf), "unsupported_answer")
        self.assertEqual(check(true_false("S1", SENTENCE)), "ok")

    def test_g4_qav_04_a_second_correct_option_is_rejected(self) -> None:
        good = mcq("S1", SENTENCE)
        same = {**good, "options": [good["options"][0], good["options"][0].upper(), *good["options"][2:]]}
        self.assertEqual(check(same), "structure")
        covered = {**good, "options": [good["options"][0], "oxidative phosphorylation", *good["options"][2:]]}
        self.assertEqual(check(covered), "second_correct_option")

    def test_g4_qav_05_near_duplicates_are_removed(self) -> None:
        first = mcq("S1", SENTENCE)
        reworded = {**first, "stem": first["stem"].replace("Complete the statement:", "Finish the statement:")}
        same_fact = {**true_false("S1", SENTENCE), "stem": "Cells make energy through oxidative phosphorylation, "
                                                           "says mitochondria theory."}
        reply = json.dumps({"questions": [first, reworded, first, same_fact]})
        result = quizgen.generate([SECTION], ScriptedLLM([reply, '{"questions": []}']), requested=5, types=("mcq", "true_false"),
                                  batch_questions=10, context_tokens=5000, max_tokens=1000)
        self.assertEqual(len(result.questions), 2)  # the reworded and repeated MCQ are dropped; the T/F is distinct
        self.assertEqual(result.dropped["near_duplicate"], 2)

    def test_g4_qav_06_tags_are_required_from_the_fixed_enums(self) -> None:
        good = mcq("S1", SENTENCE)
        for name, item in {"topic missing": {k: v for k, v in good.items() if k != "topic"},
                           "difficulty": {**good, "difficulty": "expert"},
                           "level": {**good, "cognitive_level": "create"},
                           "sources missing": {k: v for k, v in good.items() if k != "sources"}}.items():
            with self.subTest(case=name):
                self.assertNotEqual(check(item), "ok")
        quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=6)
        for question in quiz["questions"]:
            self.assertIn(question["difficulty"], quizgen.DIFFICULTIES)
            self.assertIn(question["cognitive_level"], quizgen.COGNITIVE_LEVELS)
            self.assertTrue(question["topic"])
        self.assertTrue(all(k.source_chunk_ids for k in self.keys(quiz["id"])))

    def test_g4_qav_07_question_count_bounds_and_shortage(self) -> None:
        for count, expected in ((4, 422), (31, 422), (5, 202), (30, 202)):
            with self.subTest(count=count):
                self.assertEqual(self.post_quiz(self.a, self.a_token, self.a_course,
                                                question_count=count).status_code, expected)
        self.generate()
        self.use(QuizModel(limit=6))
        short = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=10)
        self.assertEqual((short["status"], short["requested_count"], short["question_count"]), ("ready", 10, 6))
        self.assertIn("6", short["notice"])
        self.use(QuizModel(limit=3))
        failed = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=10)
        self.assertEqual((failed["status"], failed["error_code"], failed["questions"]),
                         ("failed", "insufficient_material", []))

    def test_g4_qav_08_the_server_shuffles_option_positions(self) -> None:
        self.use(QuizModel(correct_at=1))  # the model always marks option B
        quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=8, question_types=["mcq"])
        keys = {k.question_id: k for k in self.keys(quiz["id"])}
        positions = [keys[q["id"]].correct_index for q in quiz["questions"]]
        self.assertGreater(len(set(positions)), 1)
        for question in quiz["questions"]:
            key = keys[question["id"]]
            self.assertTrue(key.evidence.rstrip(".").endswith(question["options"][key.correct_index]))
        self.use(QuizModel())
        tf = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5, question_types=["true_false"])
        for question in tf["questions"]:
            self.assertEqual(question["stem"], keys_of(self, tf["id"])[question["id"]].evidence)  # not rewritten

    def test_g4_qav_09_only_generation_calls_are_made(self) -> None:
        calls, _ = quizgen.plan(6, self.app.state.settings.quiz_batch_questions)
        self.quiz_ok(self.a, self.a_token, self.a_course, question_count=6)
        self.assertEqual(len(self.llm.calls), calls)
        self.use(QuizModel(limit=6))
        llm = self.app.state.ai._provider
        self.quiz_ok(self.a, self.a_token, self.a_course, question_count=10)
        planned, _ = quizgen.plan(10, self.app.state.settings.quiz_batch_questions)
        self.assertLessEqual(len(llm.calls), planned + 1)  # at most one top-up
        for call in [*self.llm.calls, *llm.calls]:
            self.assertEqual(call[0].content, quizgen.SYSTEM_PROMPT)  # generation prompts only; nothing grades


def keys_of(case: M4Case, quiz_id: str) -> dict[str, QuizAnswerKey]:
    return {k.question_id: k for k in case.keys(quiz_id)}


class AnswerKeyTests(QuizCase):
    def setUp(self) -> None:
        super().setUp()
        self.use(QuizModel(transform=tf_distinct))

    def secrets_of(self, quiz_id: str) -> list[str]:
        out: list[str] = []
        for key in self.keys(quiz_id):
            out.append(key.evidence)
            out.extend(r for r in key.rationales if r)
        return out

    def test_g4_key_01_quiz_questions_expose_only_public_fields(self) -> None:
        quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=6)
        self.assertEqual(len(quiz["questions"]), 6)
        for question in quiz["questions"]:
            self.assertEqual(set(question), PUBLIC_QUESTION)
            if question["type"] == "true_false":
                self.assertIsNone(question["options"])
            else:
                self.assertEqual(len(question["options"]), 4)

    def test_g4_key_02_no_response_carries_any_part_of_the_key(self) -> None:
        responses: list[Any] = []
        created = self.post_quiz(self.a, self.a_token, self.a_course, question_count=6)
        responses.append(created)
        quiz_id = created.json()["id"]
        responses.append(self.get_quiz(self.a, self.a_token, quiz_id))  # while generating
        self.generate()
        responses += [self.get_quiz(self.a, self.a_token, quiz_id),
                      self.a.get(f"/api/v1/courses/{self.a_course}/quizzes", headers=self.bearer(self.a_token)),
                      self.a.post(f"/api/v1/quizzes/{quiz_id}/regenerate", headers=self.bearer(self.a_token)),
                      self.post_quiz(self.a, self.a_token, self.a_course, question_count=99),
                      self.get_quiz(self.a, self.a_token, str(uuid.uuid4()))]
        secrets = self.secrets_of(quiz_id)
        self.generate()
        responses.append(self.get_quiz(self.a, self.a_token, quiz_id))
        secrets += self.secrets_of(quiz_id)
        responses.append(self.a.delete(f"/api/v1/quizzes/{quiz_id}", headers=self.bearer(self.a_token)))
        self.assertTrue(secrets)
        for response in responses:
            body = response.text
            for secret in secrets:
                self.assertNotIn(secret, body)
            if body:
                self.assertEqual([k for k in walk_keys(response.json()) if KEY_NAME.match(k)], [])

    def test_g4_key_03_static_separation_of_the_answer_key(self) -> None:
        self.assertEqual(QuizAnswerKey.__tablename__, "quiz_answer_keys")
        spec = self.app.openapi()["components"]["schemas"]
        for name in ("QuestionOut", "QuizDetail", "QuizOut", "QuizList"):
            self.assertEqual([k for k in walk_keys(spec[name].get("properties", {})) if KEY_NAME.match(k)], [], name)
        users: set[str] = set()
        for path in (ROOT / "backend" / "app").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names} | \
                {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
            if "QuizAnswerKey" in names:
                users.add(path.relative_to(ROOT).as_posix())
        self.assertEqual(users, {"backend/app/db/models.py", "backend/app/services/generation.py",
                                 "backend/app/services/lifecycle.py"})
        self.assertFalse(any(u.startswith("backend/app/api/") for u in users))

    def test_g4_key_04_logs_jobs_and_ledger_hold_no_key_material(self) -> None:
        self.use(QuizModel(transform=lambda q: tf_distinct({**q, "sources": ["S9"]}) if q["type"] == "true_false"
                           else tf_distinct(q)))  # validation failures logged too
        with self.assertLogs(level="DEBUG") as logs:
            quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=5)
            secrets = self.secrets_of(quiz["id"])
            self.use(["__error__"])
            self.a.post(f"/api/v1/quizzes/{quiz['id']}/regenerate", headers=self.bearer(self.a_token))
            self.generate()
        self.assertTrue(secrets)
        text = "\n".join(logs.output)
        with self.db() as session:
            text += " ".join(f"{j.error_code}" for j in session.scalars(select(GenerationJob)))
            text += " ".join(f"{u.feature} {u.model}" for u in session.scalars(select(LlmUsage)))
        for secret in secrets:
            self.assertNotIn(secret, text)

    def test_g4_key_05_options_are_plain_strings_without_tells(self) -> None:
        quiz = self.quiz_ok(self.a, self.a_token, self.a_course, question_count=8, question_types=["mcq"])
        for question in quiz["questions"]:
            self.assertTrue(all(isinstance(o, str) for o in question["options"]))
            self.assertEqual(uuid.UUID(question["id"]).version, 4)
        keys = keys_of(self, quiz["id"])
        self.assertGreater(len({keys[q["id"]].correct_index for q in quiz["questions"]}), 1)

    def test_g4_key_06_invalid_and_deleted_quizzes_have_no_questions_or_keys(self) -> None:
        second = self.deck(self.a, self.a_token, self.a_course, "nerves.pptx", [FACTS[2], FACTS[3]])
        both = self.quiz_ok(self.a, self.a_token, self.a_course, document_ids=[self.doc_a, second], question_count=5)
        alone = self.quiz_ok(self.a, self.a_token, self.a_course, document_ids=[self.doc_a], question_count=5)
        self.assertTrue(self.keys(both["id"]) and self.keys(alone["id"]))
        self.assertEqual(self.a.delete(f"/api/v1/documents/{second}", headers=self.bearer(self.a_token)).status_code,
                         204)
        invalid = self.get_quiz(self.a, self.a_token, both["id"]).json()
        self.assertEqual((invalid["status"], invalid["invalid_reason"], invalid["questions"]),
                         ("invalid", "source_deleted", []))
        self.assertEqual(self.keys(both["id"]), [])
        self.a.delete(f"/api/v1/quizzes/{alone['id']}", headers=self.bearer(self.a_token))
        self.assert_same_404(self.get_quiz(self.a, self.a_token, alone["id"]), self.a_token)
        self.assertEqual(self.keys(alone["id"]), [])
        self.assertEqual(self.count(Quiz, Quiz.id == alone["id"]), 0)


if __name__ == "__main__":
    import unittest

    unittest.main()

"""Finding F-M3-05: the LLM usage ledger is the single source of truth for the daily token budget (contract UPL-16).

Deleting conversations, messages, documents or courses must never refund usage. The real ``DeepSeekProvider`` runs
over a mocked transport that reports 60 tokens per call; the budget is 100, so two answered questions spend it.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr
from sqlalchemy import delete, func, inspect, select, text

from backend.app.db.migrate import upgrade
from backend.app.db.models import LlmUsage, Message
from backend.app.db.session import create_db_engine
from backend.app.providers import DeepSeekProvider
from backend.tests.helpers import DEEPSEEK_KEY
from backend.tests.m3_base import ZEBRA, ChatCase

ROOT = Path(__file__).resolve().parents[2]
ZEBRA_Q = "Why do zebra stripes confuse predators?"
CITED = "Zebra stripes confuse predators in the savanna grasslands [S1]."


def reply(content: str = CITED) -> httpx.Response:
    return httpx.Response(200, json={"model": "deepseek-flash", "usage": {"prompt_tokens": 40, "completion_tokens": 20},
                                     "choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


class LedgerCase(ChatCase):
    def settings_overrides(self) -> dict[str, Any]:
        return {**super().settings_overrides(), "llm_daily_token_budget": 100}

    def setUp(self) -> None:
        super().setUp()
        self.zebra = self.doc(self.a, self.a_token, self.a_course, "zebra.pdf", ZEBRA)
        self.conv = self.conversation(self.a, self.a_token, self.a_course)
        self.requests: list[httpx.Request] = []
        self.replies = [CITED]

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return reply(self.replies.pop(0) if len(self.replies) > 1 else self.replies[0])

        self.app.state.ai._provider = DeepSeekProvider(api_key=SecretStr(DEEPSEEK_KEY),
                                                       transport=httpx.MockTransport(handler), sleep=lambda _: None)

    def used(self, user_id: str) -> int:
        with self.db() as session:
            return self.app.state.ledger.used_today(session, user_id)

    def spend_budget(self) -> None:
        for _ in range(2):
            self.assertEqual(self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)["state"], "answered")
        self.assertEqual(self.used(self.a_id), 120)

    def assert_still_blocked(self, conversation: str | None = None) -> None:
        calls = len(self.requests)
        conversation = conversation or self.conversation(self.a, self.a_token, self.a_course)
        with self.assertLogs("intellistudy.security", level="WARNING"):
            response = self.ask(self.a, self.a_token, conversation, ZEBRA_Q)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["type"], "about:blank#token_budget")
        self.assertEqual(len(self.requests), calls)  # no provider call
        self.assertEqual(self.used(self.a_id), 120)  # nothing refunded


class NoRefundTests(LedgerCase):
    def test_deleting_conversations_does_not_refund(self) -> None:
        self.spend_budget()
        response = self.a.delete(f"/api/v1/conversations/{self.conv}", headers=self.bearer(self.a_token))
        self.assertEqual(response.status_code, 204)
        with self.db() as session:
            self.assertEqual(session.scalar(select(func.count()).select_from(Message)), 0)
        self.assert_still_blocked()

    def test_deleting_messages_does_not_refund(self) -> None:
        self.spend_budget()
        with self.db() as session:  # no API deletes single messages; prove independence from the rows themselves
            session.execute(delete(Message))
            session.commit()
        self.assert_still_blocked(self.conv)

    def test_deleting_documents_does_not_refund(self) -> None:
        self.spend_budget()
        response = self.a.delete(f"/api/v1/documents/{self.zebra}", headers=self.bearer(self.a_token))
        self.assertEqual(response.status_code, 204)
        self.doc(self.a, self.a_token, self.a_course, "zebra-again.pdf", ZEBRA)
        self.assert_still_blocked(self.conv)

    def test_deleting_courses_does_not_refund(self) -> None:
        self.spend_budget()
        response = self.a.delete(f"/api/v1/courses/{self.a_course}", headers=self.bearer(self.a_token))
        self.assertEqual(response.status_code, 204)
        course = self.create_course(self.a_token, "Fresh course")
        self.doc(self.a, self.a_token, course, "zebra.pdf", ZEBRA)
        self.assert_still_blocked(self.conversation(self.a, self.a_token, course))

    def test_budget_is_per_user_and_resets_at_the_next_utc_day(self) -> None:
        self.spend_budget()
        self.assertEqual(self.used(self.b_id), 0)
        self.doc(self.b, self.b_token, self.b_course, "zebra.pdf", ZEBRA)
        b_conv = self.conversation(self.b, self.b_token, self.b_course)
        self.assertEqual(self.ask(self.b, self.b_token, b_conv, ZEBRA_Q).status_code, 201)
        self.clock.advance(days=1)
        fresh = self.login(self.client("10.89.0.1"), "a@example.org")
        self.assertEqual(self.ask(self.a, fresh, self.conv, ZEBRA_Q).status_code, 201)
        with self.db() as session:  # yesterday's rows are kept; only the window moved
            self.assertEqual(session.scalar(select(func.count()).select_from(LlmUsage)
                                            .where(LlmUsage.owner_id == self.a_id)), 3)


class LedgerContentTests(LedgerCase):
    def test_one_row_per_provider_call_including_refused_answers(self) -> None:
        self.replies = ["Zebra stripes confuse predators in the savanna grasslands.",  # uncited, then the repair
                        "Zebra stripes confuse predators in the savanna grasslands."]
        message = self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.assertEqual((message["state"], message["refusal_reason"]), ("refused", "uncited_answer"))
        self.assertEqual(len(self.requests), 2)
        with self.db() as session:
            rows = list(session.scalars(select(LlmUsage).where(LlmUsage.owner_id == self.a_id)))
        self.assertEqual(len(rows), 2)  # a withheld answer still cost tokens
        self.assertEqual({(r.feature, r.model, r.prompt_tokens, r.completion_tokens) for r in rows},
                         {("chat", "deepseek-flash", 40, 20)})

    def test_ledger_holds_no_content_and_links_only_to_the_user(self) -> None:
        self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)
        with self.db() as session:
            columns = {c["name"] for c in inspect(session.get_bind()).get_columns("llm_usage")}
            foreign = {fk["referred_table"] for fk in inspect(session.get_bind()).get_foreign_keys("llm_usage")}
            dump = " ".join(str(v) for row in session.execute(text("SELECT * FROM llm_usage")) for v in row)
        self.assertEqual(columns, {"id", "owner_id", "feature", "model", "prompt_tokens", "completion_tokens",
                                   "created_at"})
        self.assertEqual(foreign, {"users"})  # not conversations, messages, documents or courses
        for content in ("zebra", "Zebra", "predators", self.conv, self.a_course, self.zebra):
            self.assertNotIn(content, dump)


class StaticLedgerTests(unittest.TestCase):
    def test_the_budget_is_read_only_from_the_ledger(self) -> None:
        sources = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8")
                   for p in (ROOT / "backend" / "app").rglob("*.py")}
        readers = sorted(p for p, s in sources.items() if "llm_daily_token_budget" in s)
        self.assertEqual(readers, ["backend/app/core/config.py", "backend/app/services/usage.py"])
        for path, source in sources.items():
            with self.subTest(path=path):
                self.assertNotIn("Message.prompt_tokens", source)
                self.assertNotIn("Message.completion_tokens", source)

    def test_migration_copies_existing_message_usage_into_the_ledger(self) -> None:
        tmp = tempfile.mkdtemp(prefix="intellistudy-ledger-")
        self.addCleanup(shutil.rmtree, tmp, True)
        url = f"sqlite:///{tmp}/db.sqlite3"
        upgrade(url, "0004_conversations_messages")
        engine = create_db_engine(url)
        self.addCleanup(engine.dispose)
        user, course, conv = (str(uuid.uuid4()) for _ in range(3))
        now = "2026-11-24 10:00:00.000000"
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO users (id, email, name, password_hash, role, is_active, failed_logins, "
                              "created_at, updated_at) VALUES (:id, 'x@example.org', 'x', 'h', "
                              "'student', 1, 0, :now, :now)"), {"id": user, "now": now})
            conn.execute(text("INSERT INTO courses (id, owner_id, name, archived, created_at, updated_at) "
                              "VALUES (:id, :u, 'c', 0, :now, :now)"), {"id": course, "u": user, "now": now})
            conn.execute(text("INSERT INTO conversations (id, owner_id, course_id, title, created_at, updated_at) "
                              "VALUES (:id, :u, :c, 't', :now, :now)"), {"id": conv, "u": user, "c": course, "now": now})
            for tokens in ((30, 10), (0, 0)):
                conn.execute(text(
                    "INSERT INTO messages (id, conversation_id, owner_id, question, state, text, citations, "
                    "refusal_reason, notice, missing_terms, nearest, warnings, model, prompt_tokens, completion_tokens, "
                    "seconds, created_at, updated_at) VALUES (:id, :c, :u, 'q', 'answered', 'a', '[]', NULL, NULL, "
                    "'[]', '[]', '[]', 'deepseek-flash', :p, :o, 0, :now, :now)"),
                    {"id": str(uuid.uuid4()), "c": conv, "u": user, "p": tokens[0], "o": tokens[1], "now": now})
        upgrade(url)
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT owner_id, feature, prompt_tokens, completion_tokens FROM llm_usage")).all()
        self.assertEqual([tuple(r) for r in rows], [(user, "chat", 30, 10)])


if __name__ == "__main__":
    unittest.main()

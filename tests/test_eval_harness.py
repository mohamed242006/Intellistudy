"""Real-model evaluation harness (2026-11-15 additions): raw-reply recording, offline policy replay, cache pinning,
API-key handling and the hand-label template. Evaluation code only: the production AnswerService is not changed."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import pickle
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from ai.answering import AnswerService, GroundingPolicy, LLMError, OpenAICompatibleClient, ScriptedLLM
from ai.answering.models import Message, Sentence
from ai.retrieval import RetrievalResult
from evaluation.answer_gold import CASES
from evaluation.policy_replay import REPLAY_MISSING, replay_answer, retag_b1
from evaluation.real_model_eval import (
    RecordingLLM,
    capture_http_errors,
    file_sha256,
    label_rows,
    load_cache,
    make_client,
    redact,
    stage_answer,
)
from tests.test_answering import CACHING, NETWORK, bundle, hit, source

USER, COURSE = "u1", "c1"
LIST_SOURCE = ("the cache supports three eviction policies: least recently used removes the oldest entry, first in first out "
               "removes entries in arrival order, and random replacement removes an arbitrary entry.")


class _Retrieval:
    def __init__(self, result: RetrievalResult) -> None:
        self.result = result

    def search(self, query: str, **_: object) -> RetrievalResult:
        return self.result


def result() -> RetrievalResult:
    return RetrievalResult("q", hits=[hit(CACHING, chunk_id="a"), hit(NETWORK, chunk_id="b", citation_label="p. 2 > Net"),
                                      hit(LIST_SOURCE, chunk_id="c", citation_label="p. 3 > Policies")])


SCENARIOS = {
    "cited": ["Lru cache eviction removes the least recently used entry [S1]."],
    "partly_uncited": ["Lru cache eviction removes the least recently used entry [S1]. "
                       "Tcp handshake uses syn and ack packets between client and server."],
    "uncited_then_cited": ["Lru eviction removes the least recently used entry when the cache is full.",
                           "Lru cache eviction removes the least recently used entry [S1]."],
    "declined": ["INSUFFICIENT_CONTEXT"],
    "never_cites": ["Lru eviction removes the least recently used entry when the cache is full."],
    "unsupported": ["Quantum computers factor large primes quickly with qubits [S2]."],
}


def live(replies: list[str], grounding: GroundingPolicy | None = None):
    recorder = RecordingLLM(ScriptedLLM(replies))
    service = AnswerService(_Retrieval(result()), recorder, grounding=grounding)  # type: ignore[arg-type]
    return service.answer("What does the cache do?", user_id=USER, course_id=COURSE), recorder.replies


class RecordingTests(unittest.TestCase):
    def test_raw_replies_are_kept_verbatim_before_parsing_and_grounding(self) -> None:
        raw = "Lru cache eviction removes the least recently used entry [S1]. An invented claim about databases [S9]."
        answer, replies = live([raw])
        self.assertEqual([r["text"] for r in replies], [raw])  # the invalid tag and the dropped sentence survive here
        self.assertNotIn("S9", answer.text)
        self.assertEqual(replies[0]["attempt"], 1)
        self.assertFalse(replies[0]["repair_prompt"])

    def test_the_repair_attempt_is_recorded_and_marked(self) -> None:
        _, replies = live(SCENARIOS["uncited_then_cited"])
        self.assertEqual([r["repair_prompt"] for r in replies], [False, True])


class ReplayEquivalenceTests(unittest.TestCase):
    """Policy A replayed on recorded replies must give exactly the live AnswerService outcome."""

    def test_policy_a_replay_reproduces_the_live_answer(self) -> None:
        for name, replies in SCENARIOS.items():
            with self.subTest(scenario=name):
                answer, recorded = live(replies)
                replayed = replay_answer("What does the cache do?", result(), recorded, "A")
                self.assertEqual((replayed.text, replayed.refused, replayed.refusal_reason),
                                 (answer.text, answer.refused, answer.refusal_reason))
                self.assertEqual([c.source.chunk_id for c in replayed.citations], [c.source.chunk_id for c in answer.citations])
                self.assertEqual(replayed.llm_calls, answer.llm_calls)

    def test_policy_c_replay_reproduces_the_old_ablation(self) -> None:
        ablation = GroundingPolicy(min_terms=10**6)
        for name, replies in SCENARIOS.items():
            with self.subTest(scenario=name):
                answer, recorded = live(replies, ablation)
                replayed = replay_answer("What does the cache do?", result(), recorded, "C")
                self.assertEqual((replayed.text, replayed.refused, replayed.refusal_reason),
                                 (answer.text, answer.refused, answer.refusal_reason))

    def test_a_policy_that_needs_an_attempt_never_made_is_flagged(self) -> None:
        replayed = replay_answer("q", result(), [{"text": SCENARIOS["never_cites"][0]}], "A")
        self.assertEqual((replayed.refused, replayed.refusal_reason), (True, REPLAY_MISSING))

    def test_the_production_default_is_still_policy_a(self) -> None:
        self.assertEqual(AnswerService(_Retrieval(result()), ScriptedLLM(["x"])).grounding, GroundingPolicy())  # type: ignore[arg-type]


class PolicyB1Tests(unittest.TestCase):
    def test_list_items_under_a_cited_introduction_are_kept_by_every_policy(self) -> None:
        # Since 2026-11-23 the citation parser itself gives list items the tag of their introduction (list-aware
        # parsing), so policy A no longer drops them and B1 has nothing left to retag here.
        reply = ("The cache supports three eviction policies [S3]:\n"
                 "- least recently used removes the oldest entry\n"
                 "- first in first out removes entries in arrival order")
        a = replay_answer("q", result(), [{"text": reply}], "A")
        b1 = replay_answer("q", result(), [{"text": reply}], "B1")
        for answer in (a, b1):
            self.assertIn("- first in first out removes entries in arrival order [1]", answer.text)
        self.assertFalse(any("B1 (experimental)" in w for w in b1.warnings))

    def test_b1_retags_an_untagged_prose_sentence_from_its_neighbour(self) -> None:
        reply = ("The cache supports three eviction policies [S3]. "
                 "First in first out removes entries in arrival order.")
        a = replay_answer("q", result(), [{"text": reply}], "A")
        b1 = replay_answer("q", result(), [{"text": reply}], "B1")
        self.assertNotIn("arrival order", a.text)  # policy A drops the untagged sentence
        self.assertIn("First in first out removes entries in arrival order [1].", b1.text)
        self.assertTrue(any("B1 (experimental)" in w for w in b1.warnings))

    def test_an_unsupported_untagged_sentence_is_not_laundered_into_a_citation(self) -> None:
        sentences = [Sentence("Lru cache eviction removes the least recently used entry", ("S1",)),
                     Sentence("Quantum computers factor large primes quickly using many qubits", ())]
        retagged, count = retag_b1(sentences, bundle(source("S1"), source("S2", NETWORK)))
        self.assertEqual((count, retagged[1].tags), (0, ()))

    def test_an_untagged_sentence_takes_the_best_supporting_source_when_no_neighbour_is_tagged(self) -> None:
        sentences = [Sentence("Tcp handshake uses syn and ack packets between client and server", ())]
        retagged, count = retag_b1(sentences, bundle(source("S1"), source("S2", NETWORK)))
        self.assertEqual((count, retagged[0].tags), (1, ("S2",)))

    def test_a_retagged_sentence_still_needs_its_numbers_in_the_source(self) -> None:
        sentences = [Sentence("Lru cache eviction removes 7 entries when the cache is full", ())]
        self.assertEqual(retag_b1(sentences, bundle(source("S1")))[1], 0)


class CacheAndKeyTests(unittest.TestCase):
    def test_cache_is_pinned_by_sha256_and_must_cover_every_gold_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.pkl"
            with open(path, "wb") as handle:
                pickle.dump({"meta": {}, "results": {c.query: RetrievalResult(c.query) for c in CASES}}, handle)
            cache, digest = load_cache(path)
            self.assertEqual(digest, file_sha256(path))
            self.assertEqual(len(cache["results"]), len({c.query for c in CASES}))
            with self.assertRaises(SystemExit):
                load_cache(path, "0" * 64)
            with open(path, "wb") as handle:
                pickle.dump({"meta": {}, "results": {}}, handle)
            with self.assertRaises(SystemExit):
                load_cache(path)

    def test_hosted_api_key_comes_from_the_named_variable_and_is_never_in_messages(self) -> None:
        args = argparse.Namespace(model="m", base_url="https://api.example/v1", api_key_env="EVAL_TEST_KEY", timeout=5.0, max_retries=0)
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("EVAL_TEST_KEY", None)
            with self.assertRaises(SystemExit) as missing:
                make_client(args)
            self.assertIn("EVAL_TEST_KEY", str(missing.exception.code))
        with mock.patch.dict(os.environ, {"EVAL_TEST_KEY": "sk-secret-value"}):
            client = make_client(args)
            self.assertEqual(client._api_key, "sk-secret-value")
            self.assertNotIn("sk-secret-value", repr(vars(args)))

    def test_local_runs_keep_the_placeholder_key(self) -> None:
        args = argparse.Namespace(model="m", base_url="http://localhost:11434/v1", api_key_env="", timeout=5.0, max_retries=0)
        self.assertEqual(make_client(args)._api_key, "ollama")


class _ProviderHandler(BaseHTTPRequestHandler):
    """OpenAI-like endpoint. mode "reject": HTTP 400 whose body names the bad parameter and echoes the key (as some
    providers do); mode "ok": a cited reply."""

    mode = "reject"

    def log_message(self, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        if type(self).mode == "reject":
            key = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
            body = json.dumps({"error": {"message": f"Unsupported parameter: 'max_tokens' is not supported with this model. "
                                                    f"Use 'max_completion_tokens' instead. (key {key})",
                                         "type": "invalid_request_error", "param": "max_tokens"}}).encode()
            self.send_response(400)
        else:
            body = json.dumps({"model": "m", "choices": [{"message": {"content": "Lru cache eviction removes the least "
                               "recently used entry [S1]."}, "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


class FailFastTests(unittest.TestCase):
    """Evaluation-only fail-fast on llm_unavailable, with the provider's error body preserved (2026-11-15)."""

    KEY = "sk-test-secret-123"

    @classmethod
    def setUpClass(cls) -> None:
        cls.server = HTTPServer(("127.0.0.1", 0), _ProviderHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        _ProviderHandler.mode = "reject"
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cache = self.dir / "cache.pkl"
        with open(self.cache, "wb") as handle:  # every gold query retrieves one passage, relevance unassessed -> model called
            pickle.dump({"meta": {}, "results": {c.query: RetrievalResult(c.query, hits=[hit(CACHING)]) for c in CASES}}, handle)
        self.out = self.dir / "run.jsonl"
        self.env = mock.patch.dict(os.environ, {"EVAL_FAILFAST_KEY": self.KEY})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def args(self, *, base_url: str | None = None, limit: int = 0) -> argparse.Namespace:
        return argparse.Namespace(cache=self.cache, expect_cache_sha256="", ablate_grounding=False, policy="A", out=self.out,
                                  model="m", base_url=base_url or self.url, api_key_env="EVAL_FAILFAST_KEY", timeout=5.0,
                                  max_retries=0, limit=limit, window=0)

    def run_stage(self, args: argparse.Namespace) -> tuple[int | None, str]:
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            try:
                stage_answer(args)
                code: int | None = None
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 1
        return code, err.getvalue()

    def test_the_run_stops_at_the_first_llm_unavailable_and_appends_nothing(self) -> None:
        code, err = self.run_stage(self.args())
        self.assertEqual(code, 2)
        self.assertFalse(self.out.exists() and self.out.read_text(encoding="utf-8").strip())  # failed case not recorded
        failure = json.loads((self.dir / "run.jsonl.failure.json").read_text(encoding="utf-8"))
        self.assertEqual((failure["id"], failure["refusal_reason"]), (CASES[0].id, "llm_unavailable"))
        self.assertIn(f"STOPPED at case {CASES[0].id}", err)

    def test_the_full_provider_error_body_is_preserved_and_logged_with_the_key_redacted(self) -> None:
        _, err = self.run_stage(self.args())
        failure = json.loads((self.dir / "run.jsonl.failure.json").read_text(encoding="utf-8"))
        body = failure["raw_replies"][0]["http_errors"][0]["body"]
        self.assertEqual(failure["raw_replies"][0]["http_errors"][0]["status"], 400)
        self.assertIn("Use 'max_completion_tokens' instead", body)
        self.assertIn('"param": "max_tokens"', body)  # the whole JSON body, not a summary
        self.assertIn("Use 'max_completion_tokens' instead", err)
        for text in (body, err, (self.dir / "run.jsonl.failure.json").read_text(encoding="utf-8")):
            self.assertNotIn(self.KEY, text)
            self.assertIn("[REDACTED]", body)

    def test_re_running_after_the_cause_is_fixed_retries_the_failed_case(self) -> None:
        self.run_stage(self.args())
        _ProviderHandler.mode = "ok"
        code, _ = self.run_stage(self.args(limit=2))
        rows = [json.loads(line) for line in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertIsNone(code)
        self.assertEqual([r["id"] for r in rows], [c.id for c in CASES[:2]])
        self.assertTrue(all(not r["refused"] and r["raw_replies"][0]["text"] for r in rows))

    def test_an_unreachable_endpoint_also_stops_the_run(self) -> None:
        probe = HTTPServer(("127.0.0.1", 0), _ProviderHandler)
        port = probe.server_address[1]
        probe.server_close()  # nothing listens on this port any more
        code, err = self.run_stage(self.args(base_url=f"http://127.0.0.1:{port}/v1"))
        self.assertEqual(code, 2)
        self.assertIn("no HTTP error body", err)

    def test_a_healthy_run_is_unchanged_and_writes_no_failure_file(self) -> None:
        _ProviderHandler.mode = "ok"
        code, _ = self.run_stage(self.args(limit=3))
        self.assertIsNone(code)
        self.assertEqual(len(self.out.read_text(encoding="utf-8").splitlines()), 3)
        self.assertFalse((self.dir / "run.jsonl.failure.json").exists())

    def test_the_capture_is_temporary_and_the_production_client_semantics_are_unchanged(self) -> None:
        client = OpenAICompatibleClient("m", base_url=self.url, api_key="k", max_retries=0)
        sink: list[dict] = []
        with capture_http_errors(sink):
            with self.assertRaises(LLMError) as inside:
                client.generate([Message("user", "q")])
        with self.assertRaises(LLMError) as outside:
            client.generate([Message("user", "q")])
        self.assertEqual(str(inside.exception), str(outside.exception))  # same error, same message
        self.assertEqual(str(outside.exception), "HTTP 400 from the model endpoint")
        self.assertEqual(len(sink), 1)  # nothing captured after the block ended

    def test_answer_service_still_refuses_instead_of_raising(self) -> None:
        client = OpenAICompatibleClient("m", base_url=self.url, api_key="k", max_retries=0)
        answer = AnswerService(_Retrieval(result()), client).answer("q", user_id=USER, course_id=COURSE)  # type: ignore[arg-type]
        self.assertEqual((answer.refused, answer.refusal_reason), (True, "llm_unavailable"))

    def test_redaction_ignores_empty_secrets(self) -> None:
        self.assertEqual(redact("abc", ["", "b"]), "a[REDACTED]c")


class LabelTemplateTests(unittest.TestCase):
    def test_one_blank_row_per_substantive_sentence_of_answered_cases(self) -> None:
        cited = {"number": 1, "file_name": "notes.pdf", "citation_label": "p. 1", "text": CACHING, "context": ""}
        rows = [
            {"id": "a1", "kind": "answerable", "query": "q", "refused": False, "citations": [cited],
             "sources": [{"tag": "S1", "text": CACHING}], "text": "In short: yes. Lru removes old entries [1]. It is fast."},
            {"id": "a2", "kind": "answerable", "query": "q", "refused": True, "citations": [], "sources": [], "text": "no"},
        ]
        table = label_rows(rows, {("a1", "Lru removes old entries."): True})
        self.assertEqual([r["sentence_id"] for r in table], ["a1-1", "a1-2"])
        self.assertEqual((table[0]["citation_numbers"], table[0]["nli_entailed_by_context"]), ("1", "yes"))
        self.assertEqual((table[1]["citation_numbers"], table[1]["nli_entailed_by_context"]), ("", ""))
        self.assertTrue(all(r["human_label"] == "" and r["labeller"] == "" for r in table))


if __name__ == "__main__":
    unittest.main()

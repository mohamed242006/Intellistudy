"""M3 release gate 2.6: chat states (G3-ST-*). Confirmed precedence: refused > partial > low_confidence > answered."""

from __future__ import annotations

import itertools
from typing import Any

from ai.answering.llm import ExtractiveLLM
from ai.answering.models import Answer, Citation, GroundingReport, SourceRef
from ai.retrieval.assessment import RelevanceAssessment
from backend.app.db.models import ChatState
from backend.app.services.chat import chat_state
from backend.tests.m3_base import ZEBRA, ChatCase

ZEBRA_Q = "Why do zebra stripes confuse predators?"
PARTIAL_Q = "How do zebra stripes confuse lions and hyenas at night?"


def assessment(level: str = "strong", missing: tuple[str, ...] = ()) -> RelevanceAssessment:
    return RelevanceAssessment(level=level, top_score=0.8, top_rerank=5.0, margin=0.1, coverage=1.0,
                               missing_terms=missing, reasons=(), policy_version="test")


def source(*, low_confidence: bool = False, generated: bool = False) -> SourceRef:
    return SourceRef(tag="S1", chunk_id="c-1", document_uid="d", file_name="f.pdf", citation_label="p. 1",
                     page_number=1, slide_number=None, kind="text", text="t", score=0.9,
                     low_confidence=low_confidence, generated=generated)


def answer(*, refused: bool = False, level: str = "strong", missing: tuple[str, ...] = (), low_ocr: bool = False,
           generated: bool = False, removed: bool = False, invalid_tag: bool = False) -> Answer:
    src = source(low_confidence=low_ocr, generated=generated)
    return Answer(
        question="q", text="t [1].", refused=refused, refusal_reason="not_relevant" if refused else "",
        citations=[] if refused else [Citation(1, src)], sources=[src],
        assessment=assessment(level, missing), contains_generated_text=generated,
        grounding=GroundingReport(checked=2, supported=1, removed=(("x", "no citation"),)) if removed else GroundingReport(),
        warnings=["model cited sources that were not provided: S9"] if invalid_tag else [],
    )


class ChatStateTests(ChatCase):
    def setUp(self) -> None:
        super().setUp()
        self.conv = self.conversation(self.a, self.a_token, self.a_course)

    def test_g3_st_01_answered(self) -> None:
        self.doc(self.a, self.a_token, self.a_course, "zebra.pdf", ZEBRA)
        self.set_model(ExtractiveLLM())
        message = self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.assertEqual((message["state"], message["refusal_reason"], message["notice"]), ("answered", None, None))
        self.assertTrue(message["citations"])

    def test_g3_st_02_every_refusal_reason(self) -> None:
        empty = self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)  # no document yet
        self.doc(self.a, self.a_token, self.a_course, "zebra.pdf", ZEBRA)
        cases: dict[str, Any] = {
            "not_relevant": (ExtractiveLLM(), "What is the capital of France?"),
            "model_declined": (["INSUFFICIENT_CONTEXT"], ZEBRA_Q),
            "uncited_answer": (["Zebra stripes confuse predators."], ZEBRA_Q),
            "unsupported_claims": (["Penguins live in Antarctica and eat krill fish daily [S1]."], ZEBRA_Q),
            "llm_unavailable": (None, ZEBRA_Q),
        }
        results = {"no_results": empty}
        for reason, (model, question) in cases.items():
            if model is None:
                self.app.state.ai._provider = None
            else:
                self.set_model(model)
            results[reason] = self.ask_ok(self.a, self.a_token, self.conv, question)
        for reason, message in results.items():
            with self.subTest(reason=reason):
                self.assertEqual((message["state"], message["refusal_reason"]), ("refused", reason))
                self.assertTrue(message["notice"])
                self.assertEqual(message["citations"], [])
                if reason != "no_results":
                    self.assertTrue(message["nearest"], reason)  # the closest material is offered

    def test_g3_st_03_partial(self) -> None:
        self.doc(self.a, self.a_token, self.a_course, "zebra.pdf", ZEBRA)
        self.set_model(ExtractiveLLM())
        message = self.ask_ok(self.a, self.a_token, self.conv, PARTIAL_Q)
        self.assertEqual(message["state"], "partial")
        self.assertTrue({"lions", "hyenas"} <= set(message["missing_terms"]))
        self.assertIn("lions", message["notice"])
        self.assertTrue(message["citations"])

    def test_g3_st_04_each_low_confidence_condition(self) -> None:
        for condition in ("level", "low_ocr", "generated", "removed", "invalid_tag"):
            with self.subTest(condition=condition):
                kwargs = {"level": "weak"} if condition == "level" else {condition: True}
                self.assertEqual(chat_state(answer(**kwargs)), ChatState.LOW_CONFIDENCE)
        self.doc(self.a, self.a_token, self.a_course, "zebra.pdf", ZEBRA)
        self.set_model(["Zebra stripes confuse predators in the savanna grasslands [S1]. "
                        "Penguins live in Antarctica and eat krill fish daily [S1]."])
        removed = self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.set_model(["Zebra stripes confuse predators in the savanna grasslands [S1][S9]."])
        invalid = self.ask_ok(self.a, self.a_token, self.conv, ZEBRA_Q)
        self.assertEqual((removed["state"], invalid["state"]), ("low_confidence", "low_confidence"))
        self.assertTrue(removed["notice"] and invalid["notice"])

    def test_g3_st_05_precedence_is_refused_partial_low_confidence_answered(self) -> None:
        flags = ("refused", "missing", "low")
        for combo in itertools.product([False, True], repeat=3):
            on = dict(zip(flags, combo, strict=True))
            built = answer(refused=on["refused"], missing=("x",) if on["missing"] else (), removed=on["low"])
            expected = (ChatState.REFUSED if on["refused"] else ChatState.PARTIAL if on["missing"]
                        else ChatState.LOW_CONFIDENCE if on["low"] else ChatState.ANSWERED)
            with self.subTest(**on):
                self.assertEqual(chat_state(built), expected)
        self.assertEqual([s.value for s in ChatState], ["refused", "partial", "low_confidence", "answered"])

    def test_g3_st_06_states_are_stored_and_read_back(self) -> None:
        self.doc(self.a, self.a_token, self.a_course, "zebra.pdf", ZEBRA)
        created = []
        for model, question in ((ExtractiveLLM(), ZEBRA_Q), (ExtractiveLLM(), PARTIAL_Q),
                                (["Zebra stripes confuse predators in the savanna grasslands [S1][S9]."], ZEBRA_Q),
                                (["INSUFFICIENT_CONTEXT"], ZEBRA_Q)):
            self.set_model(model)
            self.clock.advance(1)  # history is ordered by creation time, as with the real clock
            created.append(self.ask_ok(self.a, self.a_token, self.conv, question))
        self.assertEqual([m["state"] for m in created], ["answered", "partial", "low_confidence", "refused"])
        stored = self.a.get(f"/api/v1/conversations/{self.conv}", headers=self.bearer(self.a_token)).json()["messages"]
        self.assertEqual(stored, created)


if __name__ == "__main__":
    import unittest

    unittest.main()

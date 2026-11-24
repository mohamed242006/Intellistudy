"""M4 test helpers: multi-page documents, the generation runner, and deterministic scripted models that build valid
summaries and quizzes from the sources in their prompt (so tests can then break one property at a time)."""

from __future__ import annotations

import io
import json
import re
from collections.abc import Callable, Sequence
from typing import Any

import fitz
from pptx import Presentation
from sqlalchemy import func, select

from ai.answering.llm import ScriptedLLM
from ai.answering.models import Message
from backend.app.db.models import GenerationJob, LlmUsage, QuizAnswerKey, QuizQuestion
from backend.tests.m3_base import ChatCase

SOURCE = re.compile(r'<source id="(S\d+)"[^>]*>\n(.*?)\n</source>', re.DOTALL)
SENTENCE = re.compile(r"(?<=[.!?])\s+")
DISTRACTORS = ("Purple quantum teapots", "Silent marble giraffes", "Frozen copper violins", "Lazy neon volcanoes",
               "Hollow velvet comets", "Brittle cobalt lanterns")

#: distinct facts per page (each sentence is a possible question)
FACTS = [
    "Mitochondria produce cellular energy through oxidative phosphorylation. Ribosomes assemble proteins from "
    "messenger templates. Lysosomes digest worn organelles with acidic enzymes.",
    "Photosynthesis converts sunlight into chemical energy inside chloroplasts. Stomata regulate gas exchange on leaf "
    "surfaces. Xylem vessels transport water upward from roots.",
    "Neurons transmit electrical impulses along myelinated axons. Synapses release neurotransmitters into narrow "
    "clefts. Dendrites receive incoming signals from neighbouring cells.",
    "Enzymes lower activation energy for biochemical reactions. Substrates bind enzymes at specific active sites. "
    "Temperature changes alter enzyme folding and activity.",
]


def pdf_pages(texts: Sequence[str]) -> bytes:
    document = fitz.open()
    for number, text in enumerate(texts, start=1):
        page = document.new_page()
        page.insert_text((50, 60), f"Chapter {number}", fontsize=22, fontname="hebo")  # a real heading per page
        page.insert_textbox(fitz.Rect(50, 90, 550, 800), text, fontsize=11)
    data = document.tobytes()
    document.close()
    return bytes(data)


def pptx_slides(texts: Sequence[str]) -> bytes:
    """One slide per text, each its own section (parent) with the title as heading."""
    deck = Presentation()
    for number, text in enumerate(texts, start=1):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = f"Topic {number}"
        slide.placeholders[1].text = text
    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def sources_of(messages: Sequence[Message]) -> list[tuple[str, str]]:
    return SOURCE.findall(messages[-1].content)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE.split(text) if len(re.findall(r"[A-Za-z]{3,}", s)) >= 4]


def summary_reply(messages: Sequence[Message]) -> str:
    """One block per source: its first sentence, cited."""
    blocks = []
    for tag, text in sources_of(messages):
        first = next(iter(sentences(text)), "")
        if first:
            blocks.append(f"### [{tag}]\n{first.rstrip('.')} [{tag}].")
    return "\n\n".join(blocks)


def mcq(tag: str, sentence: str, *, correct_at: int = 0, n: int = 0) -> dict[str, Any]:
    words = sentence.rstrip(".").split()
    correct = " ".join(words[-3:])
    wrong = [DISTRACTORS[(n + i) % len(DISTRACTORS)] for i in range(3)]
    options = wrong[:correct_at] + [correct] + wrong[correct_at:]
    return {"type": "mcq", "stem": f"Complete the statement: {' '.join(words[:-3])} ...?", "options": options,
            "correct_index": correct_at, "rationales": [f"Rationale {i} for option" for i in range(4)],
            "sources": [tag], "evidence": sentence, "topic": "Cell biology", "difficulty": "easy",
            "cognitive_level": "remember"}


def true_false(tag: str, sentence: str) -> dict[str, Any]:
    return {"type": "true_false", "stem": sentence, "answer": True, "rationale": "Stated in the source.",
            "sources": [tag], "evidence": sentence, "topic": "Cell biology", "difficulty": "medium",
            "cognitive_level": "understand"}


class QuizModel:
    """Builds valid questions from the prompt's sources, one per sentence, alternating types when both are asked."""

    def __init__(self, *, correct_at: int | None = 0, transform: Callable[[dict[str, Any]], Any] | None = None,
                 limit: int | None = None) -> None:
        self.correct_at = correct_at
        self.transform = transform
        self.limit = limit
        self.made = 0

    def __call__(self, messages: Sequence[Message]) -> str:
        prompt = messages[-1].content
        wanted = int(re.search(r"Write (\d+) ", prompt).group(1))  # type: ignore[union-attr]
        both = "multiple-choice and true/false" in prompt or "true/false and multiple-choice" in prompt
        only_tf = "true/false" in prompt and not both
        questions: list[Any] = []
        for tag, text in sources_of(messages):
            for sentence in sentences(text):
                if len(questions) >= wanted or (self.limit is not None and self.made >= self.limit):
                    break
                kind_tf = only_tf or (both and self.made % 2 == 1)
                at = self.correct_at if self.correct_at is not None else self.made % 4
                item = true_false(tag, sentence) if kind_tf else mcq(tag, sentence, correct_at=at, n=self.made)
                self.made += 1
                questions.append(self.transform(item) if self.transform else item)
        return json.dumps({"questions": questions})


class M4Case(ChatCase):
    def pdf(self, client: Any, token: str, course_id: str, name: str, pages: Sequence[str] = tuple(FACTS)) -> str:
        document_id = str(self.upload_ok(client, token, course_id, (name, pdf_pages(pages)))[0]["id"])
        self.process()
        return document_id

    def deck(self, client: Any, token: str, course_id: str, name: str, texts: Sequence[str] = tuple(FACTS)) -> str:
        document_id = str(self.upload_ok(client, token, course_id, (name, pptx_slides(texts)))[0]["id"])
        self.process()
        return document_id

    def generate(self) -> int:
        return int(self.app.state.generation_runner.run_pending())

    def use(self, replies: Any) -> ScriptedLLM:
        llm: ScriptedLLM = self.set_model(replies)
        return llm

    # ------------------------------------------------------------------------------------------ summaries
    def post_summary(self, client: Any, token: str, document_id: str, **body: Any) -> Any:
        return client.post(f"/api/v1/documents/{document_id}/summary", json=body, headers=self.bearer(token))

    def get_summary(self, client: Any, token: str, document_id: str) -> Any:
        return client.get(f"/api/v1/documents/{document_id}/summary", headers=self.bearer(token))

    def summary_ok(self, client: Any, token: str, document_id: str, **body: Any) -> dict[str, Any]:
        response = self.post_summary(client, token, document_id, **body)
        self.assertIn(response.status_code, (200, 202), response.text)
        self.generate()
        view = self.get_summary(client, token, document_id)
        self.assertEqual(view.status_code, 200, view.text)
        return dict(view.json())

    # -------------------------------------------------------------------------------------------- quizzes
    def post_quiz(self, client: Any, token: str, course_id: str, **body: Any) -> Any:
        return client.post(f"/api/v1/courses/{course_id}/quizzes", json=body, headers=self.bearer(token))

    def get_quiz(self, client: Any, token: str, quiz_id: str) -> Any:
        return client.get(f"/api/v1/quizzes/{quiz_id}", headers=self.bearer(token))

    def quiz_ok(self, client: Any, token: str, course_id: str, **body: Any) -> dict[str, Any]:
        response = self.post_quiz(client, token, course_id, **body)
        self.assertEqual(response.status_code, 202, response.text)
        self.generate()
        view = self.get_quiz(client, token, response.json()["id"])
        self.assertEqual(view.status_code, 200, view.text)
        return dict(view.json())

    # ---------------------------------------------------------------------------------------- inspection
    def count(self, model: Any, *where: Any) -> int:
        with self.db() as session:
            return int(session.scalar(select(func.count()).select_from(model).where(*where)) or 0)

    def jobs(self) -> int:
        return self.count(GenerationJob)

    def usage(self, user_id: str) -> int:
        with self.db() as session:
            return int(session.scalar(select(func.coalesce(func.sum(
                LlmUsage.prompt_tokens + LlmUsage.completion_tokens), 0)).where(LlmUsage.owner_id == user_id)) or 0)

    def keys(self, quiz_id: str) -> list[QuizAnswerKey]:
        with self.db() as session:
            return list(session.scalars(select(QuizAnswerKey).where(QuizAnswerKey.quiz_id == quiz_id)))

    def questions(self, quiz_id: str) -> list[QuizQuestion]:
        with self.db() as session:
            return list(session.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id)
                                        .order_by(QuizQuestion.position)))

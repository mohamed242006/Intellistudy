"""Data types of the answer layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai.retrieval.assessment import RelevanceAssessment

# --- refusal reasons (stable strings: logged, tested and shown to the UI) ---------------------------------------
NO_RESULTS = "no_results"  # nothing retrieved
NOT_RELEVANT = "not_relevant"  # retrieval judged the material unrelated to the question
MODEL_DECLINED = "model_declined"  # the model said the sources do not contain the answer
UNCITED = "uncited_answer"  # the model answered without citing any provided source
UNSUPPORTED = "unsupported_claims"  # every sentence failed the grounding check
LLM_UNAVAILABLE = "llm_unavailable"  # the model could not be reached


@dataclass(frozen=True, slots=True)
class Message:
    role: str  # system | user | assistant
    content: str


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = ""
    latency_s: float = 0.0


@dataclass(frozen=True, slots=True)
class SourceRef:
    """One piece of retrieved material offered to the model, with everything needed to cite it."""

    tag: str  # "S1"
    chunk_id: str
    document_uid: str
    file_name: str
    citation_label: str
    page_number: int
    slide_number: int | None
    kind: str
    text: str
    score: float
    ocr_confidence: float | None = None
    low_confidence: bool = False
    generated: bool = False  # contains model-generated text (a figure description), not only the author's words
    figure_label: str = ""
    context: str = ""  # wider section text (parent chunk), when budget allowed

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "chunk_id": self.chunk_id,
            "document_uid": self.document_uid,
            "file_name": self.file_name,
            "citation_label": self.citation_label,
            "page_number": self.page_number,
            "slide_number": self.slide_number,
            "kind": self.kind,
            "score": round(self.score, 4),
            "ocr_confidence": self.ocr_confidence,
            "low_confidence": self.low_confidence,
            "generated": self.generated,
            "figure_label": self.figure_label,
        }


@dataclass(frozen=True, slots=True)
class ContextBundle:
    question: str
    sources: tuple[SourceRef, ...]
    tokens: int
    omitted: int = 0  # retrieved hits left out (budget, duplicates)
    warnings: tuple[str, ...] = ()

    def by_tag(self, tag: str) -> SourceRef | None:
        return next((s for s in self.sources if s.tag == tag), None)


@dataclass(frozen=True, slots=True)
class Citation:
    number: int  # the [n] shown to the reader
    source: SourceRef

    def to_dict(self) -> dict[str, Any]:
        return {"number": self.number, **self.source.to_dict()}


@dataclass(frozen=True, slots=True)
class Sentence:
    text: str
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GroundingReport:
    checked: int = 0
    supported: int = 0
    removed: tuple[tuple[str, str], ...] = ()  # (sentence, reason)
    support_score: float = 1.0  # mean share of a sentence's content words found in its cited sources

    @property
    def clean(self) -> bool:
        return not self.removed


@dataclass(slots=True)
class Answer:
    question: str
    text: str
    refused: bool = False
    refusal_reason: str = ""
    citations: list[Citation] = field(default_factory=list)
    sources: list[SourceRef] = field(default_factory=list)  # everything the model saw
    nearest: list[SourceRef] = field(default_factory=list)  # closest material, offered on refusal
    confidence: str = ""  # strong | weak | "" (not assessed)
    assessment: RelevanceAssessment | None = None
    grounding: GroundingReport | None = None
    contains_generated_text: bool = False
    warnings: list[str] = field(default_factory=list)
    model: str = ""
    prompt_version: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "text": self.text,
            "refused": self.refused,
            "refusal_reason": self.refusal_reason,
            "citations": [c.to_dict() for c in self.citations],
            "nearest": [s.to_dict() for s in self.nearest],
            "confidence": self.confidence,
            "contains_generated_text": self.contains_generated_text,
            "warnings": list(self.warnings),
            "model": self.model,
            "prompt_version": self.prompt_version,
            "usage": {
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "calls": self.llm_calls,
            },
            "seconds": round(self.seconds, 3),
        }

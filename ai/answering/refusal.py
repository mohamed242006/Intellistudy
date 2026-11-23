"""Refusal logic: when the assistant must say "I could not find this in your materials" instead of answering.

Two stages. *Before* the model is called, retrieval's relevance assessment decides: nothing retrieved, or material judged
unrelated, means no model call at all (cheaper, and nothing to hallucinate from). *After* the model replies, the service
refuses when the model declines, cites nothing, or when no sentence survives the grounding check. A refusal carries the
closest material, so the reader can look for themselves.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.answering.models import (
    LLM_UNAVAILABLE,
    MODEL_DECLINED,
    NO_RESULTS,
    NOT_RELEVANT,
    UNCITED,
    UNSUPPORTED,
    SourceRef,
)
from ai.retrieval.assessment import NONE, WEAK
from ai.retrieval.models import RetrievalResult


@dataclass(frozen=True, slots=True)
class RefusalPolicy:
    unassessed: str = "proceed"  # no calibrated relevance policy for these models: "proceed" (warn) or "refuse"
    caution_on_weak: bool = True  # weak match: answer, but tell the model to cover only what is clearly supported


@dataclass(frozen=True, slots=True)
class PreCheck:
    refuse: bool
    reason: str = ""
    caution: bool = False
    warning: str = ""


def pre_check(result: RetrievalResult, policy: RefusalPolicy) -> PreCheck:
    if not result.hits:
        return PreCheck(True, NO_RESULTS)
    assessment = result.assessment
    if assessment is None:
        if policy.unassessed == "refuse":
            return PreCheck(True, NOT_RELEVANT, warning="relevance could not be assessed")
        return PreCheck(False, warning="relevance was not assessed (no calibrated policy for the configured models)")
    if assessment.level == NONE:
        return PreCheck(True, NOT_RELEVANT)
    return PreCheck(False, caution=policy.caution_on_weak and assessment.level == WEAK)


def message(reason: str, *, missing_terms: tuple[str, ...] = (), nearest: SourceRef | None = None) -> str:
    """The text shown to the reader for a refusal."""
    if reason == LLM_UNAVAILABLE:
        return "The answer service is temporarily unavailable. Please try again in a moment."
    if reason == NO_RESULTS:
        base = "I couldn't find anything in your uploaded materials that relates to this question."
    elif reason == MODEL_DECLINED:
        base = "The material I found doesn't contain enough information to answer this."
    elif reason in (UNCITED, UNSUPPORTED):
        base = "I couldn't put together an answer that I can back with your uploaded materials."
    else:
        base = "I couldn't find this in your uploaded materials."
        if missing_terms:
            base += f" Nothing I found mentions: {', '.join(missing_terms[:5])}."
    if nearest is not None:
        base += f" The closest material is {nearest.file_name}, {nearest.citation_label}."
    return base

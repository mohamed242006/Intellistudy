"""Hallucination prevention: check every sentence of an answer against the sources it cites.

The model may paraphrase, so the checks are deliberately lexical and conservative about what they *remove*, but strict
about what must be present:
    * a substantive sentence must cite at least one offered source;
    * the sentence's content words must be found in its cited sources (``min_support``);
    * every number in the sentence must occur in a cited source (no invented figures);
    * every quoted string must occur verbatim in a cited source.
Failing sentences are removed, never silently rewritten. ``min_support`` is a provisional value: it has been
exercised with an extractive generator only and must be calibrated on a real model's answers before it is trusted.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ai.answering.models import ContextBundle, GroundingReport, Sentence
from ai.retrieval.assessment import content_terms

_NUMBER = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")
_QUOTED = re.compile(r"\"([^\"]{4,})\"|“([^”]{4,})”")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class GroundingPolicy:
    min_support: float = 0.35  # share of a sentence's content words that must appear in its cited sources
    min_terms: int = 3  # shorter sentences ("In summary:", "Yes.") are framing, not claims
    check_numbers: bool = True
    check_quotes: bool = True


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(text)}


def _norm(text: str) -> str:
    return _SPACES.sub(" ", text).strip().casefold()


def check(
    sentences: Sequence[Sentence], bundle: ContextBundle, policy: GroundingPolicy | None = None
) -> tuple[list[Sentence], GroundingReport]:
    """Return the sentences that pass and a report naming each removed sentence and why."""
    policy = policy or GroundingPolicy()
    kept: list[Sentence] = []
    removed: list[tuple[str, str]] = []
    scores: list[float] = []
    checked = 0
    for sentence in sentences:
        terms = content_terms(sentence.text)
        numbers = _numbers(sentence.text)
        cited = [s for s in (bundle.by_tag(t) for t in sentence.tags) if s is not None]
        trivial = len(terms) < policy.min_terms and not numbers
        if trivial:
            kept.append(sentence)
            continue
        checked += 1
        if not cited:
            removed.append((sentence.text, "no citation"))
            continue
        haystack_text = " ".join(f"{s.text} {s.context} {s.citation_label} {s.file_name}" for s in cited)
        have = set(content_terms(haystack_text))
        support = sum(1 for t in terms if t in have) / len(terms) if terms else 1.0
        if policy.check_numbers and not numbers <= _numbers(haystack_text):
            missing = sorted(numbers - _numbers(haystack_text))
            removed.append((sentence.text, f"number(s) not in the cited source: {', '.join(missing)}"))
            continue
        if policy.check_quotes:
            body = _norm(haystack_text)
            quotes = [a or b for a, b in _QUOTED.findall(sentence.text)]
            bad = [q for q in quotes if _norm(q) not in body]
            if bad:
                removed.append((sentence.text, f"quotation not found in the cited source: {bad[0][:40]}"))
                continue
        if support < policy.min_support:
            removed.append((sentence.text, f"low support ({support:.2f}) in the cited source"))
            continue
        scores.append(support)
        kept.append(sentence)
    report = GroundingReport(
        checked=checked,
        supported=len(scores),
        removed=tuple(removed),
        support_score=round(sum(scores) / len(scores), 3) if scores else (1.0 if not checked else 0.0),
    )
    return kept, report

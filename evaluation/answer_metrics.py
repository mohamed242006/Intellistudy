"""Metrics for the real-model evaluation of the answer layer (pure functions; see docs/real_model_eval_plan.md).

Instruments
    * deterministic fact matching against hand-written gold facts (``answer_gold``) -> correctness, completeness;
    * deterministic source matching (gold sources) -> citation correctness;
    * an independent NLI model (``NliJudge``) -> faithfulness and attribution. It is deliberately NOT the answer layer's
      own grounding code, so the system is not graded by its own rules;
    * number checks (a figure in the answer that appears in no provided source is fabricated).

Definitions (n = cases of the stated kind)
    correctness    correct = fact recall >= min_facts and no forbidden string; rate over ALL answerable cases
                   (a refusal counts as not correct) and over the answered ones
    completeness   mean fact recall (found / total facts) over answerable cases (refusal = 0) and over answered ones
    citation       hit = at least one cited source is a gold source; precision = gold sources / cited sources;
                   coverage = cited substantive sentences / all substantive sentences (added 2026-11-15)
    faithfulness   share of answer sentences entailed (p >= 0.5) by the retrieved context given to the model
    hallucination  answer-level: an answered case with an unsupported sentence, a fabricated number or a forbidden string
                   (biased toward long answers); sentence-level pooled; sentence-level mean per answer (added 2026-11-15,
                   every answer weighs the same)
    attribution    sentence-level: share of cited sentences entailed by the sources they cite; share of ALL substantive
                   sentences that are cited AND entailed by their own cited sources (added 2026-11-15); fact-level:
                   share of gold facts present in the answer that are found in a cited source
    refusal        recall on refuse-expected cases, false-refusal rate on answerable ones, overall decision accuracy

"Substantive sentence" = a sentence of the final answer kept by ``answer_sentences`` (pure framing is skipped). Each
case also records ``sentence_details``: per sentence, its citation numbers, entailment by the whole context and
entailment by its own cited sources (None when uncited) - the per-sentence record needed for hand validation.

2026-11-15 fix: ``grounding_removed`` is now recorded for refused cases as well (previously ``score_case`` returned
before setting it, so ``grounding_sentences_removed_by_system`` under-counted). Reporting only: no headline metric
used that field.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ai.retrieval.assessment import content_terms
from evaluation.answer_gold import GoldCase, normalize

_NUMBER = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_MARK = re.compile(r"\s*\[\d+(?:\s*,\s*\d+)*\]")
ENTAIL_THRESHOLD = 0.5
_FRAMING = frozenset({"short", "summary", "yes", "sure", "certainly", "overall", "thus", "therefore", "hence", "okay"})


# ----------------------------------------------------------------------------------------------- statistics
def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval of a proportion (honest about small samples)."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3))


def rate(successes: int, n: int) -> dict[str, Any]:
    return {"n": n, "k": successes, "rate": round(successes / n, 3) if n else None, "ci95": wilson(successes, n)}


# ----------------------------------------------------------------------------------------------- facts / sources
@dataclass(frozen=True, slots=True)
class FactScore:
    found: tuple[bool, ...]
    correct: bool
    completeness: float
    forbidden_hit: bool


def score_facts(case: GoldCase, answer_text: str) -> FactScore:
    found = tuple(f.present_in(answer_text) for f in case.facts)
    forbidden = any(normalize(x) in normalize(answer_text) for x in case.forbidden)
    total = len(case.facts)
    correct = bool(total) and sum(found) >= case.min_facts and not forbidden
    return FactScore(found, correct, (sum(found) / total) if total else 0.0, forbidden)


def source_is_gold(case: GoldCase, file_name: str, label: str, text: str) -> bool:
    """A cited source is acceptable if it matches the gold criteria or itself contains a gold fact."""
    gold = case.gold
    if gold is None:
        return False
    if gold.file.lower() in file_name.lower() and (
        any(c.lower() in text.lower() for c in gold.contains) or (gold.heading and gold.heading.lower() in label.lower())
    ):
        return True
    return any(f.present_in(f"{label} {text}") for f in case.facts)


@dataclass(frozen=True, slots=True)
class CitationScore:
    cited: int
    relevant: int
    hit: bool
    precision: float


def score_citations(case: GoldCase, cited: Sequence[dict[str, Any]]) -> CitationScore:
    relevant = sum(source_is_gold(case, c["file_name"], c["citation_label"], c["text"]) for c in cited)
    return CitationScore(len(cited), relevant, relevant > 0, (relevant / len(cited)) if cited else 0.0)


def fact_attribution(case: GoldCase, answer_found: Sequence[bool], cited: Sequence[dict[str, Any]]) -> tuple[int, int]:
    """(facts present in the answer, of which found in a cited source)."""
    present = attributed = 0
    cited_text = " ".join(f"{c['citation_label']} {c['text']} {c.get('context', '')}" for c in cited)
    for fact, in_answer in zip(case.facts, answer_found, strict=True):
        if in_answer:
            present += 1
            attributed += fact.present_in(cited_text)
    return present, attributed


# ----------------------------------------------------------------------------------------------- numbers / sentences
def numbers_in(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(text)}


def fabricated_numbers(answer_text: str, source_texts: Sequence[str]) -> list[str]:
    """Numbers in the answer (citation marks excluded) found in none of the provided sources."""
    allowed: set[str] = set()
    for text in source_texts:
        allowed |= numbers_in(text)
    return sorted(n for n in numbers_in(_MARK.sub("", answer_text)) if n not in allowed)


def answer_sentences(answer_text: str) -> list[tuple[str, tuple[int, ...]]]:
    """Sentences of a final answer with their ``[n]`` citation numbers; trivial framing sentences are dropped."""
    out: list[tuple[str, tuple[int, ...]]] = []
    for raw in _SENTENCE.split(answer_text):
        marks = tuple(int(n) for group in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", raw) for n in re.findall(r"\d+", group))
        clean = _MARK.sub("", raw).strip(" -*\t")
        if [t for t in content_terms(clean) if t not in _FRAMING] or numbers_in(clean):  # only pure framing is skipped
            out.append((clean, marks))
    return out


# ----------------------------------------------------------------------------------------------- NLI judge
class Entailment(Protocol):
    def entailment(self, premises: Sequence[str], hypothesis: str) -> float: ...


class NliJudge:
    """Max entailment probability of ``hypothesis`` over windows of the premises (cross-encoder NLI)."""

    def __init__(self, model: str = "cross-encoder/nli-deberta-v3-small", window_words: int = 140, stride_words: int = 90) -> None:
        from sentence_transformers import CrossEncoder

        self._model = CrossEncoder(model)
        labels = {v.lower(): k for k, v in self._model.config.id2label.items()}
        self._entail = labels["entailment"]
        self._window, self._stride = window_words, stride_words
        self.name = model
        self._cache: dict[tuple[str, str], float] = {}

    def _windows(self, premise: str) -> list[str]:
        words = premise.split()
        if len(words) <= self._window:
            return [premise]
        return [" ".join(words[i : i + self._window]) for i in range(0, len(words) - self._window + self._stride, self._stride)]

    def entailment(self, premises: Sequence[str], hypothesis: str) -> float:
        import numpy as np

        windows = [w for p in premises for w in self._windows(p) if w.strip()]
        if not windows or not hypothesis.strip():
            return 0.0
        pairs = [(w, hypothesis) for w in windows if (w, hypothesis) not in self._cache]
        if pairs:
            logits = np.asarray(self._model.predict(pairs, batch_size=16, show_progress_bar=False))
            exp = np.exp(logits - logits.max(axis=1, keepdims=True))
            for pair, prob in zip(pairs, (exp / exp.sum(axis=1, keepdims=True))[:, self._entail], strict=True):
                self._cache[pair] = float(prob)
        return max(self._cache[(w, hypothesis)] for w in windows)


# ----------------------------------------------------------------------------------------------- per-case scoring
@dataclass(slots=True)
class CaseScore:
    id: str
    kind: str
    expect: str
    refused: bool
    reason: str
    # answerable
    facts_found: int = 0
    facts_total: int = 0
    correct: bool | None = None
    completeness: float | None = None
    forbidden_hit: bool = False
    # citations
    cited: int = 0
    citation_hit: bool | None = None
    citation_precision: float | None = None
    facts_in_answer: int = 0
    facts_attributed: int = 0
    # faithfulness / hallucination (answered cases)
    sentences: int = 0
    sentences_supported: int = 0
    cited_sentences: int = 0
    cited_sentences_supported: int = 0
    unsupported: list[str] = field(default_factory=list)
    sentence_details: list[dict[str, Any]] = field(default_factory=list)
    fabricated: list[str] = field(default_factory=list)
    hallucinated: bool | None = None
    over_answered: bool | None = None  # answered although a refusal was expected
    grounding_removed: int = 0


def score_case(case: GoldCase, row: dict[str, Any], judge: Entailment | None) -> CaseScore:
    refused = bool(row["refused"])
    score = CaseScore(case.id, case.kind, case.expect, refused, row.get("refusal_reason", ""))
    if case.expect != "answer":
        score.over_answered = (not refused) if case.expect == "refuse" else None
    if case.facts:
        score.facts_total = len(case.facts)
    score.grounding_removed = int(row.get("grounding_removed", 0))  # before the refusal return (2026-11-15 fix)
    if refused:
        if case.expect == "answer":
            score.correct, score.completeness = False, 0.0
        return score

    text = row["text"]
    sources = row["sources"]
    by_number = {c["number"]: c for c in row["citations"]}
    cited = [by_number[n] for n in sorted(by_number)]
    context = [f"{s['text']} {s.get('context', '')}" for s in sources]

    if case.expect == "answer" or case.facts:
        facts = score_facts(case, text)
        score.facts_found, score.correct = sum(facts.found), facts.correct
        score.completeness, score.forbidden_hit = facts.completeness, facts.forbidden_hit
        score.facts_in_answer, score.facts_attributed = fact_attribution(case, facts.found, cited)
    if case.gold is not None:
        cites = score_citations(case, cited)
        score.cited, score.citation_hit, score.citation_precision = cites.cited, cites.hit, cites.precision
    else:
        score.cited = len(cited)

    score.fabricated = fabricated_numbers(text, context)
    sentences = answer_sentences(text)
    score.sentences = len(sentences)
    if judge is not None:
        for sentence, marks in sentences:
            entailed = judge.entailment(context, sentence) >= ENTAIL_THRESHOLD
            if entailed:
                score.sentences_supported += 1
            else:
                score.unsupported.append(sentence[:160])
            by_cited: bool | None = None
            if marks:
                premises = [f"{by_number[m]['text']} {by_number[m].get('context', '')}" for m in marks if m in by_number]
                score.cited_sentences += 1
                by_cited = bool(premises) and judge.entailment(premises, sentence) >= ENTAIL_THRESHOLD
                score.cited_sentences_supported += by_cited
            score.sentence_details.append(
                {"sentence": sentence, "citations": list(marks), "entailed_by_context": entailed, "entailed_by_cited": by_cited}
            )
    else:
        score.cited_sentences = sum(1 for _, marks in sentences if marks)
    score.hallucinated = bool(score.unsupported or score.fabricated or score.forbidden_hit)
    return score


# ----------------------------------------------------------------------------------------------- aggregation
def aggregate(scores: Sequence[CaseScore]) -> dict[str, Any]:
    ans = [s for s in scores if s.expect == "answer"]
    answered = [s for s in ans if not s.refused]
    refuse_expected = [s for s in scores if s.expect == "refuse"]
    all_answered = [s for s in scores if not s.refused]
    sentences = sum(s.sentences for s in all_answered)
    supported = sum(s.sentences_supported for s in all_answered)
    cited_sentences = sum(s.cited_sentences for s in all_answered)
    cited_supported = sum(s.cited_sentences_supported for s in all_answered)
    with_sentences = [s for s in all_answered if s.sentences]
    per_answer = [(s.sentences - s.sentences_supported) / s.sentences for s in with_sentences]
    facts_present = sum(s.facts_in_answer for s in answered)
    facts_attr = sum(s.facts_attributed for s in answered)
    scored_decisions = [s for s in scores if s.expect in ("answer", "refuse")]
    correct_decisions = sum((not s.refused) == (s.expect == "answer") for s in scored_decisions)
    refused_all = [s for s in scored_decisions if s.refused]
    by_kind: dict[str, dict[str, Any]] = {}
    for kind in sorted({s.kind for s in scores}):
        group = [s for s in scores if s.kind == kind]
        by_kind[kind] = {"n": len(group), "refused": sum(s.refused for s in group), "answered": sum(not s.refused for s in group)}
    return {
        "cases": len(scores),
        "by_kind": by_kind,
        "correctness": {
            "of_all_answerable": rate(sum(bool(s.correct) for s in ans), len(ans)),
            "of_answered": rate(sum(bool(s.correct) for s in answered), len(answered)),
        },
        "completeness": {
            "mean_of_all_answerable": round(sum(s.completeness or 0.0 for s in ans) / len(ans), 3) if ans else None,
            "mean_of_answered": round(sum(s.completeness or 0.0 for s in answered) / len(answered), 3) if answered else None,
        },
        "citation": {
            "answered_with_a_gold_source_cited": rate(sum(bool(s.citation_hit) for s in answered), len(answered)),
            "mean_precision": round(sum(s.citation_precision or 0.0 for s in answered) / len(answered), 3) if answered else None,
            "answers_without_any_citation": sum(s.cited == 0 for s in all_answered),
            "coverage": rate(cited_sentences, sentences),
        },
        "faithfulness": {"sentences_entailed_by_context": rate(supported, sentences)},
        "hallucination": {
            "answer_level_of_answered": rate(sum(bool(s.hallucinated) for s in all_answered), len(all_answered)),
            "sentence_level": rate(sentences - supported, sentences),
            "sentence_level_mean_per_answer": round(sum(per_answer) / len(per_answer), 3) if per_answer else None,
            "answers_with_fabricated_numbers": rate(sum(bool(s.fabricated) for s in all_answered), len(all_answered)),
            "answered_when_refusal_expected": rate(sum(bool(s.over_answered) for s in refuse_expected), len(refuse_expected)),
        },
        "attribution": {
            "cited_sentences_entailed_by_their_sources": rate(cited_supported, cited_sentences),
            "substantive_sentences_attributed": rate(cited_supported, sentences),
            "gold_facts_found_in_a_cited_source": rate(facts_attr, facts_present),
        },
        "refusal": {
            "recall_on_refuse_expected": rate(sum(s.refused for s in refuse_expected), len(refuse_expected)),
            "false_refusal_on_answerable": rate(sum(s.refused for s in ans), len(ans)),
            "precision_of_refusals": rate(sum(s.expect == "refuse" for s in refused_all), len(refused_all)),
            "decision_accuracy": rate(correct_decisions, len(scored_decisions)),
        },
        "grounding_sentences_removed_by_system": sum(s.grounding_removed for s in scores),
    }

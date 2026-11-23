"""Judge whether retrieval found material that can answer the question.

Dense similarity alone cannot do this: unrelated questions score 0.45-0.65 against any corpus while true
answers score 0.6-0.85, so one threshold either refuses real questions or accepts nonsense. The assessment
combines independent signals and leaves the decision to a versioned, measured policy
(``ai/retrieval/calibration.py``, calibrated with ``evaluation/``):

* vector similarity of the best hit and its margin over the next one;
* cross-encoder score of the best hit, when a reranker is configured;
* lexical coverage - the share of the question's content words that appear in the best hits, their
  headings or the file name. "tuition fee" missing from a corpus that only mentions "university" shows up
  here, and the missing words are handed to the answer layer.

The result is advice (``strong`` / ``weak`` / ``none``); the answer layer still owns the refusal.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ai.retrieval.models import RetrievedChunk

STRONG = "strong"
WEAK = "weak"
NONE = "none"

_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    ["a", "about", "above", "after", "again", "against", "all", "also", "am", "an", "and", "any", "are", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her", "here", "hers", "him", "his", "how", "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most", "my", "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "out", "over", "own", "same", "she", "should", "so", "some", "such", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your", "give", "tell", "explain", "describe", "show", "list", "used", "use", "using", "one", "two", "get", "make"]
)


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def _terms(text: str) -> dict[str, str]:
    """Content words of ``text`` as ``{stem: first surface form}`` (stopwords and 1-2 letter words removed)."""
    found: dict[str, str] = {}
    for word in _WORD.findall(text.lower()):
        if word in _STOPWORDS or (len(word) < 3 and not word.isdigit()):
            continue
        found.setdefault(_stem(word), word)
    return found


def content_terms(text: str) -> list[str]:
    """Distinct content-word stems of ``text``."""
    return list(_terms(text))


@dataclass(frozen=True, slots=True)
class RetrievalPolicy:
    """Thresholds that turn signals into a level. Produced by calibration; never edited by feel."""

    version: str
    strong_vector: float
    weak_vector: float
    strong_rerank: float
    weak_rerank: float
    min_coverage_vector: float  # below this the level drops one step (strong -> weak -> none)
    min_coverage_rerank: float
    embedding_model: str = ""  # models the numbers were measured with; "" = not checked
    reranker_model: str = ""
    coverage_hits: int = 3  # how many top hits are searched for the question's words
    demote_references: bool = True


@dataclass(frozen=True, slots=True)
class RelevanceAssessment:
    level: str  # strong | weak | none
    top_score: float  # cosine similarity of the best hit
    top_rerank: float | None
    margin: float  # best minus second-best cosine (0 with a single hit)
    coverage: float  # share of the question's content words found in the best hits
    missing_terms: tuple[str, ...]  # question words found nowhere in the best hits
    reasons: tuple[str, ...]
    policy_version: str

    @property
    def answerable(self) -> bool:
        return self.level != NONE


def lexical_coverage(query: str, hits: Sequence[RetrievedChunk]) -> tuple[float, tuple[str, ...]]:
    terms = _terms(query)
    if not terms:
        return 1.0, ()
    haystack: set[str] = set()
    for hit in hits:
        haystack.update(_terms(" ".join((hit.text, " ".join(hit.heading_path), hit.file_name))))
    missing = tuple(surface for stem, surface in terms.items() if stem not in haystack)
    return (len(terms) - len(missing)) / len(terms), missing


def level_for(signal: float, strong_at: float, weak_at: float, coverage: float, min_coverage: float) -> str:
    """The decision rule, shared by the service and the calibration harness so they cannot drift apart."""
    level = STRONG if signal >= strong_at else WEAK if signal >= weak_at else NONE
    if coverage < min_coverage and level != NONE:
        level = WEAK if level == STRONG else NONE
    return level


def assess(
    query: str, hits: Sequence[RetrievedChunk], policy: RetrievalPolicy, *, use_rerank: bool = True
) -> RelevanceAssessment:
    if not hits:
        return RelevanceAssessment(NONE, 0.0, None, 0.0, 0.0, tuple(_terms(query).values()), ("no hits",), policy.version)

    best = hits[0]
    margin = best.score - hits[1].score if len(hits) > 1 else 0.0
    coverage, missing = lexical_coverage(query, hits[: policy.coverage_hits])
    reasons: list[str] = []

    if use_rerank and best.rerank_score is not None:
        signal, strong_at, weak_at, name = best.rerank_score, policy.strong_rerank, policy.weak_rerank, "rerank"
        min_coverage = policy.min_coverage_rerank
    else:
        signal, strong_at, weak_at, name = best.score, policy.strong_vector, policy.weak_vector, "vector"
        min_coverage = policy.min_coverage_vector
    by_score = level_for(signal, strong_at, weak_at, 1.0, min_coverage)
    reasons.append(f"{name} {signal:.2f} (strong>={strong_at:.2f}, weak>={weak_at:.2f}) -> {by_score}")
    level = level_for(signal, strong_at, weak_at, coverage, min_coverage)
    if level != by_score:
        reasons.append(f"coverage {coverage:.2f} < {min_coverage:.2f} (missing: {', '.join(missing)}) -> {level}")
    return RelevanceAssessment(level, best.score, best.rerank_score, margin, coverage, missing, tuple(reasons), policy.version)

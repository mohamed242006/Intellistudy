"""Offline grounding-policy replay: re-run the answer layer's post-processing on RECORDED model replies.

EVALUATION ONLY. Nothing here is imported by product code, and the production default (``AnswerService`` with
``GroundingPolicy()``, called "policy A" in docs/real_model_eval_report.md) is not changed by this module.

Because citation parsing and the grounding check are deterministic, the same raw replies can be scored under different
policies without calling the model again, so a policy comparison is not confounded by generation noise:

    A   the shipped behaviour: every substantive sentence must cite an offered source and pass the support, number and
        quote checks; failing sentences are removed.
    C   the 2026-10 ablation ("--ablate-grounding"): ``GroundingPolicy(min_terms=10**6)``, i.e. sentences without a number
        are kept unchecked, cited or not. This is a PARTIAL ablation (sentences with numbers are still checked).
    B1  EXPERIMENTAL deterministic repair-and-retag (not adopted): before removal, every untagged substantive sentence
        is offered a source - first the tags of the nearest preceding model-tagged sentence (covers list items under a
        cited intro), then of the nearest following one, then each offered source by lexical support - and keeps the
        first assignment under which it passes the full policy-A check. Sentences that pass under no source are still
        removed by the normal check. Risk ("citation laundering"): a sentence from the model's own knowledge can be
        attached to a source that merely shares words; judge it with per-sentence attribution, not with correctness.

Replay limits (recorded as warnings on each answer):
    * a second attempt is only available if the live run made one; its prompt carried policy A's repair note. If a
      policy needs an attempt that was never generated, the case is refused with reason ``replay_missing_attempt``.
    * timing is not replayed; token counts are copied from the recorded replies.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from ai.answering import citations as citation_tools
from ai.answering.context import ContextBuilder
from ai.answering.grounding import GroundingPolicy, check
from ai.answering.llm import INSUFFICIENT
from ai.answering.models import MODEL_DECLINED, UNCITED, UNSUPPORTED, Answer, ContextBundle, Sentence
from ai.answering.prompt import PROMPT_VERSION
from ai.answering.refusal import RefusalPolicy, pre_check
from ai.answering.service import AnswerService
from ai.retrieval.assessment import content_terms
from ai.retrieval.models import RetrievalResult

POLICIES = ("A", "B1", "C")
REPLAY_MISSING = "replay_missing_attempt"


def grounding_for(policy: str) -> GroundingPolicy:
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}; expected one of {POLICIES}")
    return GroundingPolicy(min_terms=10**6) if policy == "C" else GroundingPolicy()


def _passes(text: str, tags: tuple[str, ...], bundle: ContextBundle, policy: GroundingPolicy) -> bool:
    kept, _ = check([Sentence(text, tags)], bundle, policy)
    return bool(kept)


def _support(text: str, haystack: str) -> float:
    terms = content_terms(text)
    if not terms:
        return 0.0
    have = set(content_terms(haystack))
    return sum(1 for t in terms if t in have) / len(terms)


def retag_b1(
    sentences: Sequence[Sentence], bundle: ContextBundle, policy: GroundingPolicy | None = None
) -> tuple[list[Sentence], int]:
    """Policy B1: give untagged substantive sentences a source they pass under; return (sentences, number retagged)."""
    policy = policy or GroundingPolicy()
    original = list(sentences)
    out = list(sentences)
    retagged = 0
    for i, sentence in enumerate(original):
        if sentence.tags or _passes(sentence.text, (), bundle, policy):  # tagged, or trivial framing (kept untagged)
            continue
        before = next((original[j].tags for j in range(i - 1, -1, -1) if original[j].tags), ())
        after = next((original[j].tags for j in range(i + 1, len(original)) if original[j].tags), ())
        ranked = sorted(
            bundle.sources,
            key=lambda s: -_support(sentence.text, f"{s.text} {s.context} {s.citation_label} {s.file_name}"),
        )
        candidates: list[tuple[str, ...]] = []
        for tags in (before, after, *((s.tag,) for s in ranked)):
            if tags and tags not in candidates:
                candidates.append(tags)
        for tags in candidates:
            if _passes(sentence.text, tags, bundle, policy):
                out[i] = Sentence(sentence.text, tags)
                retagged += 1
                break
    return out, retagged


def replay_answer(
    question: str,
    result: RetrievalResult,
    replies: Sequence[dict[str, Any]],
    policy: str,
    *,
    context_builder: ContextBuilder | None = None,
    refusal: RefusalPolicy | None = None,
    max_attempts: int = 2,
    model: str = "",
) -> Answer:
    """Mirror of ``AnswerService.answer`` that reads replies from ``replies`` (``{"text": ..., ...}`` per attempt).

    With policy "A" it must reproduce the live answer exactly (tested against ``AnswerService``).
    """
    grounding = grounding_for(policy)
    started = time.time()
    text = question.strip()
    answer = Answer(question=text, text="", assessment=result.assessment, model=model, prompt_version=PROMPT_VERSION,
                    warnings=list(result.warnings))
    bundle = (context_builder or ContextBuilder()).build(text, result)
    answer.warnings.extend(bundle.warnings)
    decision = pre_check(result, refusal or RefusalPolicy())
    if decision.warning:
        answer.warnings.append(decision.warning)
    if decision.refuse:
        return AnswerService._refuse(answer, decision.reason, bundle, started)

    answer.sources = list(bundle.sources)
    answer.confidence = result.assessment.level if result.assessment is not None else ""
    for attempt in range(max_attempts):
        last = attempt + 1 == max_attempts
        if attempt >= len(replies):
            answer.warnings.append(f"replay: policy {policy} needed attempt {attempt + 1}, which the live run never made")
            return AnswerService._refuse(answer, REPLAY_MISSING, bundle, started)
        if attempt > 0:
            answer.warnings.append("replay: attempt 2 was generated with policy A's repair note")
        reply = replies[attempt]
        answer.llm_calls += 1
        answer.prompt_tokens += int(reply.get("prompt_tokens", 0))
        answer.completion_tokens += int(reply.get("completion_tokens", 0))
        reply_text = str(reply.get("text", "")).strip()
        if reply_text.upper().startswith(INSUFFICIENT):
            return AnswerService._refuse(answer, MODEL_DECLINED, bundle, started)

        parsed = citation_tools.parse(reply_text, bundle)
        if parsed.invalid_tags:
            answer.warnings.append(f"model cited sources that were not provided: {', '.join(parsed.invalid_tags)}")
        sentences = list(parsed.sentences)
        if policy == "B1":
            sentences, retagged = retag_b1(sentences, bundle, grounding)
            if retagged:
                answer.warnings.append(f"B1 (experimental): {retagged} untagged sentence(s) retagged")
        if not any(s.tags for s in sentences):
            if last:
                return AnswerService._refuse(answer, UNCITED, bundle, started)
            continue
        kept, report = check(sentences, bundle, grounding)
        if not any(s.tags for s in kept):
            answer.grounding = report
            if last:
                return AnswerService._refuse(answer, UNSUPPORTED, bundle, started)
            continue
        final_text, cited = citation_tools.render(kept, bundle)
        answer.text, answer.citations, answer.grounding = final_text, cited, report
        answer.contains_generated_text = any(c.source.generated for c in cited)
        for removed_text, reason in report.removed:
            answer.warnings.append(f"removed an unsupported sentence ({reason}): {removed_text[:80]}")
        if answer.contains_generated_text:
            answer.warnings.append("the answer relies on AI-generated figure text")
        answer.seconds = time.time() - started
        return answer
    return AnswerService._refuse(answer, UNCITED, bundle, started)  # unreachable with max_attempts >= 1

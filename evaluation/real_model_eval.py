"""Real-model evaluation of the answer layer (plan: docs/real_model_eval_plan.md).

Three resumable stages so that every model sees identical retrieval and scoring is decoupled from generation:

    python -m evaluation.real_model_eval retrieve --index-dir DIR --cache CACHE.pkl      # builds the index in-process
    python -m evaluation.real_model_eval answer   --cache CACHE.pkl --model qwen2.5-3b-8k \\
           --base-url http://localhost:11434/v1 --out RUN.jsonl [--policy A|C]
    python -m evaluation.real_model_eval score    --run RUN.jsonl --tag qwen --out-dir evaluation/results
    python -m evaluation.real_model_eval replay   --cache CACHE.pkl --run RUN.jsonl --policy A|B1|C --out RUN_B1.jsonl
    python -m evaluation.real_model_eval label-template --run RUN.jsonl --out SENTENCES.csv

``answer`` appends one JSON row per case (resume = re-run the same command). ``score`` needs no model server: it uses an
NLI cross-encoder as an independent judge and writes metrics, a failure breakdown and a manual-audit sample.

Additions of 2026-11-15 (evaluation only; the production AnswerService is unchanged):
    * every row stores ``raw_replies``: the model's reply to every attempt, BEFORE citation parsing and grounding;
    * every row stores ``retrieval_cache_sha256``; ``answer`` refuses to append to a run made from a different cache, so
      two models compared on one cache provably saw identical retrieval (``--expect-cache-sha256`` pins it explicitly);
    * ``--api-key-env NAME`` reads the key from that environment variable (hosted APIs); the key is never printed or
      written. Without it the local Ollama placeholder key is used, as before;
    * ``--policy`` selects the live grounding policy: A (shipped default) or C (= the old ``--ablate-grounding``).
      The experimental policy B1 exists only in ``replay`` (offline, on recorded replies; see policy_replay.py);
    * ``label-template`` writes the hand-label sheet for validating the NLI judge sentence by sentence.

Fail-fast (2026-11-15, evaluation only): ``answer`` stops with exit code 2 at the first ``llm_unavailable`` case
(HTTP error, timeout, unreachable endpoint). The case is not appended (re-running the command retries it); it is written
to ``<out>.failure.json`` with the provider's full HTTP error body, which ``OpenAICompatibleClient`` itself discards and
which is captured here by a temporary urllib error handler (API key redacted), and the body is printed to stderr.
``AnswerService`` and ``OpenAICompatibleClient`` are unchanged: in production a model outage is still a refusal.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import io
import json
import logging
import os
import pickle
import random
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

from ai.answering import AnswerService, OpenAICompatibleClient
from ai.answering.llm import LLMClient
from ai.answering.models import LLM_UNAVAILABLE, Answer, LLMResponse, Message
from ai.retrieval.models import RetrievalResult
from evaluation.answer_gold import CASES, GoldCase
from evaluation.answer_metrics import NliJudge, aggregate, answer_sentences, rate, score_case, source_is_gold
from evaluation.index_builder import COURSE, USER
from evaluation.policy_replay import POLICIES, grounding_for, replay_answer

K = 6
LIVE_POLICIES = ("A", "C")  # B1 is experimental and offline only (replay)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def redact(text: str, secrets: Sequence[str]) -> str:
    """Remove secret values (the API key) from text before it is logged or written."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


class _CapturingErrorHandler(urllib.request.HTTPDefaultErrorHandler):
    """Reads the body of every HTTP error response into ``sink``, then raises the same ``HTTPError`` as the default
    handler (with the body re-attached), so the production client's error handling is unchanged."""

    def __init__(self, sink: list[dict[str, Any]]) -> None:
        self.sink = sink

    def http_error_default(self, req: urllib.request.Request, fp: IO[bytes] | None, code: int, msg: str, hdrs: Any) -> Any:
        body = fp.read() if fp is not None else b""
        self.sink.append({"status": code, "url": req.full_url, "body": body.decode("utf-8", "replace")})
        raise urllib.error.HTTPError(req.full_url, code, msg, hdrs, io.BytesIO(body))


@contextmanager
def capture_http_errors(sink: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    """EVALUATION ONLY: while active, the provider's error bodies (which ``OpenAICompatibleClient`` discards) are kept.

    Installs a process-wide urllib opener for the duration of the block and restores the previous one afterwards.
    """
    previous = getattr(urllib.request, "_opener", None)
    urllib.request.install_opener(urllib.request.build_opener(_CapturingErrorHandler(sink)))
    try:
        yield sink
    finally:
        urllib.request.install_opener(previous)  # None restores urllib's default opener


class RecordingLLM:
    """Wraps an ``LLMClient`` and keeps every raw reply (before citation parsing and grounding) for the current case.

    Failed calls are recorded too, with the provider's HTTP error bodies when ``http_errors`` is the sink of an active
    ``capture_http_errors`` block; ``secrets`` are redacted from them.
    """

    def __init__(self, inner: LLMClient, *, http_errors: list[dict[str, Any]] | None = None,
                 secrets: Sequence[str] = ()) -> None:
        self.inner = inner
        self.model_name = inner.model_name
        self.replies: list[dict[str, Any]] = []
        self._http_errors = http_errors
        self._secrets = tuple(secrets)

    def reset(self) -> None:
        self.replies = []

    def generate(self, messages: Sequence[Message], *, temperature: float = 0.0, max_tokens: int = 700) -> LLMResponse:
        seen = len(self._http_errors) if self._http_errors is not None else 0
        try:
            reply = self.inner.generate(messages, temperature=temperature, max_tokens=max_tokens)
        except Exception as exc:
            errors = (self._http_errors or [])[seen:]
            self.replies.append({
                "attempt": len(self.replies) + 1, "error": redact(f"{type(exc).__name__}: {exc}", self._secrets),
                "http_errors": [{**e, "body": redact(e["body"], self._secrets)} for e in errors],
            })
            raise
        self.replies.append({
            "attempt": len(self.replies) + 1, "text": reply.text, "model": reply.model, "finish_reason": reply.finish_reason,
            "prompt_tokens": reply.prompt_tokens, "completion_tokens": reply.completion_tokens,
            "latency_s": round(reply.latency_s, 3), "repair_prompt": any("previous reply was not acceptable" in m.content for m in messages),
        })
        return reply


def load_cache(path: Path, expect_sha256: str = "") -> tuple[dict[str, Any], str]:
    digest = file_sha256(path)
    if expect_sha256 and digest != expect_sha256:
        raise SystemExit(f"retrieval cache {path} has sha256 {digest}, expected {expect_sha256}: refusing to run")
    with open(path, "rb") as handle:
        cache = pickle.load(handle)  # our own file
    missing = [c.id for c in CASES if c.query not in cache["results"]]
    if missing:
        raise SystemExit(f"retrieval cache lacks {len(missing)} gold queries (e.g. {missing[:5]}): rebuild it with `retrieve`")
    return cache, digest


def make_client(args: argparse.Namespace) -> OpenAICompatibleClient:
    """Local servers get the placeholder key; hosted APIs read the key from ``--api-key-env`` (never printed)."""
    if args.api_key_env:
        if not os.environ.get(args.api_key_env):
            raise SystemExit(f"environment variable {args.api_key_env} is not set")
        return OpenAICompatibleClient(args.model, base_url=args.base_url, api_key_env=args.api_key_env,
                                      timeout=args.timeout, max_retries=args.max_retries)
    return OpenAICompatibleClient(args.model, base_url=args.base_url, api_key="ollama", timeout=args.timeout,
                                  max_retries=args.max_retries)


# ----------------------------------------------------------------------------------------------- stage 1
def stage_retrieve(args: argparse.Namespace) -> None:
    from ai.embedding import BgeEmbedder
    from ai.retrieval import RetrievalService
    from ai.retrieval.rerank import CrossEncoderReranker
    from evaluation.index_builder import build_index, open_stores

    build_index(args.index_dir, force=args.rebuild)
    store, parents = open_stores(args.index_dir)
    service = RetrievalService(BgeEmbedder(), store, parent_store=parents, reranker=CrossEncoderReranker())
    results: dict[str, RetrievalResult] = {}
    for case in CASES:
        results[case.query] = service.search(case.query, user_id=USER, course_id=COURSE, k=K)
    meta = {"policy": service.policy.version, "k": K, "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(args.cache, "wb") as handle:
        pickle.dump({"meta": meta, "results": results}, handle)
    print(f"cached retrieval for {len(results)} cases -> {args.cache}")


class CachedRetrieval:
    """Stands in for RetrievalService: answers ``search`` from the cache, so every model sees identical context."""

    def __init__(self, results: dict[str, RetrievalResult]) -> None:
        self._results = results

    def search(self, query: str, **_: Any) -> RetrievalResult:
        return self._results[query]


# ----------------------------------------------------------------------------------------------- stage 2
def _row(case: GoldCase, answer: Answer, result: RetrievalResult, window: int | None,
         *, raw_replies: list[dict[str, Any]], cache_sha256: str, policy: str) -> dict[str, Any]:
    sources = [dataclasses.asdict(s) for s in answer.sources]
    return {
        "id": case.id, "kind": case.kind, "query": case.query, "refused": answer.refused,
        "refusal_reason": answer.refusal_reason, "text": answer.text,
        "citations": [{**dataclasses.asdict(c.source), "number": c.number} for c in answer.citations],
        "sources": sources,
        "retrieved": [{"file_name": h.file_name, "citation_label": h.citation_label, "text": h.text[:2500]} for h in result.hits],
        "assessment": answer.assessment.level if answer.assessment else None,
        "missing_terms": list(answer.assessment.missing_terms) if answer.assessment else [],
        "grounding_removed": len(answer.grounding.removed) if answer.grounding else 0,
        "grounding_removed_detail": [list(r) for r in (answer.grounding.removed if answer.grounding else ())],
        "warnings": answer.warnings, "llm_calls": answer.llm_calls, "prompt_tokens": answer.prompt_tokens,
        "completion_tokens": answer.completion_tokens, "seconds": round(answer.seconds, 2),
        "confidence": answer.confidence, "model": answer.model, "context_window": window,
        "raw_replies": raw_replies, "retrieval_cache_sha256": cache_sha256, "grounding_policy": policy,
    }


def _existing_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def stage_answer(args: argparse.Namespace) -> None:
    cache, digest = load_cache(args.cache, args.expect_cache_sha256)
    policy = "C" if args.ablate_grounding else args.policy
    existing = _existing_rows(args.out)
    mixed = {r.get("retrieval_cache_sha256") for r in existing} - {digest}
    if mixed:
        raise SystemExit(f"{args.out} was made from a different retrieval cache ({sorted(map(str, mixed))}); use a new --out")
    if any(r.get("grounding_policy", policy) != policy for r in existing):
        raise SystemExit(f"{args.out} was made with a different grounding policy; use a new --out")
    secrets = [os.environ.get(args.api_key_env, "")] if args.api_key_env else []
    http_errors: list[dict[str, Any]] = []
    llm = RecordingLLM(make_client(args), http_errors=http_errors, secrets=secrets)
    service = AnswerService(CachedRetrieval(cache["results"]), llm, k=K, grounding=grounding_for(policy))  # type: ignore[arg-type]
    done = {r["id"] for r in existing}
    cases = [c for c in CASES if c.id not in done]
    if args.limit:
        cases = cases[: args.limit]
    print(f"{len(done)} done, {len(cases)} to run with {args.model} (policy {policy}, cache sha256 {digest[:12]})", flush=True)
    with capture_http_errors(http_errors):
        for number, case in enumerate(cases, start=1):
            _answer_case(args, service, llm, case, number, len(cases), cache, digest, policy)


def fail_fast(args: argparse.Namespace, row: dict[str, Any]) -> None:
    """Stop the run at the first ``llm_unavailable`` (evaluation only; AnswerService still refuses as in production).

    The failed case is NOT appended to the run file, so re-running the same command retries it; it is written to
    ``<out>.failure.json`` with the provider's error body (API key redacted) and the body is logged to stderr.
    """
    failure_path = args.out.with_name(args.out.name + ".failure.json")
    failure_path.write_text(json.dumps(row, indent=1, ensure_ascii=False), encoding="utf-8")
    bodies = [e["body"] for r in row["raw_replies"] for e in r.get("http_errors", [])]
    errors = [r.get("error", "") for r in row["raw_replies"] if r.get("error")]
    print(f"STOPPED at case {row['id']}: the model endpoint failed (llm_unavailable); nothing was appended for this case.",
          file=sys.stderr)
    for error in errors:
        print(f"  client error: {error}", file=sys.stderr)
    for body in bodies:
        print(f"  provider error body: {body}", file=sys.stderr)
    if not bodies:
        print("  (no HTTP error body: the endpoint was unreachable or timed out)", file=sys.stderr)
    print(f"  details: {failure_path}. Fix the cause and re-run the same command to resume.", file=sys.stderr, flush=True)
    raise SystemExit(2)


def _answer_case(args: argparse.Namespace, service: AnswerService, llm: RecordingLLM, case: GoldCase, number: int,
                 total: int, cache: dict[str, Any], digest: str, policy: str) -> None:
    started = time.time()
    llm.reset()
    answer = service.answer(case.query, user_id=USER, course_id=COURSE)
    row = _row(case, answer, cache["results"][case.query], args.window,
               raw_replies=list(llm.replies), cache_sha256=digest, policy=policy)
    if answer.refused and answer.refusal_reason == LLM_UNAVAILABLE:
        fail_fast(args, row)
    if args.window and row["prompt_tokens"] and row["prompt_tokens"] > args.window - 700:
        row["warnings"].append(f"PROMPT NEAR CONTEXT WINDOW ({row['prompt_tokens']} of {args.window}): answer may be truncated")
    with args.out.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[{number}/{total}] {case.id:4s} refused={answer.refused!s:5s} {answer.refusal_reason or '':16s} "
          f"{time.time() - started:5.1f}s tokens={answer.prompt_tokens}", flush=True)


def stage_replay(args: argparse.Namespace) -> None:
    """Score a different grounding policy on the replies a live run recorded (no model call)."""
    cache, digest = load_cache(args.cache, args.expect_cache_sha256)
    rows = _existing_rows(args.run)
    if not rows:
        raise SystemExit(f"{args.run} has no rows")
    stale = [r["id"] for r in rows if r.get("retrieval_cache_sha256") not in (None, digest)]
    if stale:
        raise SystemExit(f"{len(stale)} rows of {args.run} were made from a different retrieval cache")
    cases = {c.id: c for c in CASES}
    out_rows = []
    for row in rows:
        if "raw_replies" not in row:
            raise SystemExit(f"{args.run} has no raw_replies (made before 2026-11-15): it cannot be replayed")
        case = cases[row["id"]]
        result = cache["results"][case.query]
        replies = [r for r in row["raw_replies"] if "text" in r]
        answer = replay_answer(case.query, result, replies, args.policy, model=row.get("model", ""))
        new = _row(case, answer, result, row.get("context_window"), raw_replies=row["raw_replies"], cache_sha256=digest,
                   policy=args.policy)
        new["replayed_from"] = str(args.run)
        out_rows.append(new)
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out_rows), encoding="utf-8")
    print(f"replayed {len(out_rows)} cases under policy {args.policy} -> {args.out}")


LABEL_COLUMNS = (
    "sentence_id", "case_id", "kind", "query", "sentence", "citation_numbers", "cited_locations", "cited_source_text",
    "all_context_excerpt", "nli_entailed_by_context", "human_label", "human_notes", "labeller", "labelled_on",
)


def label_rows(rows: Sequence[dict[str, Any]], nli: dict[tuple[str, str], bool] | None = None) -> list[dict[str, str]]:
    """One row per substantive answer sentence (the same sentences the NLI judge scores), label columns left blank."""
    out: list[dict[str, str]] = []
    for row in rows:
        if row["refused"]:
            continue
        by_number = {c["number"]: c for c in row["citations"]}
        for index, (sentence, marks) in enumerate(answer_sentences(row["text"]), start=1):
            cited = [by_number[m] for m in marks if m in by_number]
            judged = (nli or {}).get((row["id"], sentence))
            out.append({
                "sentence_id": f"{row['id']}-{index}", "case_id": row["id"], "kind": row["kind"], "query": row["query"],
                "sentence": sentence, "citation_numbers": " ".join(map(str, marks)),
                "cited_locations": " | ".join(f"[{c['number']}] {c['file_name']} - {c['citation_label']}" for c in cited),
                "cited_source_text": " || ".join(f"[{c['number']}] {c['text']} {c.get('context', '')}".strip() for c in cited)[:4000],
                "all_context_excerpt": " || ".join(f"{s['tag']}: {s['text']}" for s in row["sources"])[:6000],
                "nli_entailed_by_context": "" if judged is None else ("yes" if judged else "no"),
                "human_label": "", "human_notes": "", "labeller": "", "labelled_on": "",
            })
    return out


def stage_label_template(args: argparse.Namespace) -> None:
    rows = _existing_rows(args.run)
    nli: dict[tuple[str, str], bool] = {}
    if args.cases:  # cases_TAG.json from `score` (2026-11-15 or later) carries the judge's per-sentence verdicts
        for scored in json.loads(args.cases.read_text(encoding="utf-8")):
            for detail in scored.get("sentence_details") or []:
                nli[(scored["id"], detail["sentence"])] = bool(detail["entailed_by_context"])
    table = label_rows(rows, nli)
    with open(args.out, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_COLUMNS)
        writer.writeheader()
        writer.writerows(table)
    print(f"{len(table)} sentences -> {args.out} (labels blank: this is a template, not a completed validation)")


# ----------------------------------------------------------------------------------------------- stage 3
def failure_breakdown(case_rows: dict[str, dict[str, Any]], cases: dict[str, GoldCase]) -> dict[str, Any]:
    """Why answerable cases were not answered correctly: retrieval vs refusal vs wrong answer."""
    buckets: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    gold_in_retrieved = 0
    answerable = [c for c in cases.values() if c.expect == "answer"]
    for case in answerable:
        row = case_rows.get(case.id)
        if row is None:
            continue
        has_gold = any(source_is_gold(case, h["file_name"], h["citation_label"], h["text"]) for h in row["retrieved"])
        gold_in_retrieved += has_gold
    for case in answerable:
        row = case_rows.get(case.id)
        if row is None:
            continue
        from evaluation.answer_metrics import score_facts

        has_gold = any(source_is_gold(case, h["file_name"], h["citation_label"], h["text"]) for h in row["retrieved"])
        if row["refused"]:
            kind = "refused_by_retrieval_policy" if row["refusal_reason"] in ("no_results", "not_relevant") else f"refused_by_{row['refusal_reason']}"
        elif score_facts(case, row["text"]).correct:
            continue
        else:
            kind = "wrong_answer_gold_in_context" if has_gold else "wrong_answer_gold_not_retrieved"
        if not row["refused"] or kind.startswith("refused_by_retrieval"):
            kind += "" if has_gold else " (gold source not retrieved)" if kind.startswith("refused_by_retrieval") else ""
        buckets[kind] += 1
        if len(examples[kind]) < 6:
            examples[kind].append(case.id)
    return {"answerable_with_gold_in_retrieved_context": rate(gold_in_retrieved, len(answerable)), "failures": dict(buckets), "examples": dict(examples)}


def by_tag(scores, cases: dict[str, GoldCase]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    tags = sorted({t for c in cases.values() for t in c.tags if c.expect == "answer"})
    for tag in tags:
        group = [s for s in scores if tag in cases[s.id].tags and s.expect == "answer"]
        out[tag] = rate(sum(bool(s.correct) for s in group), len(group))
    return out


def stage_score(args: argparse.Namespace) -> None:
    rows = [json.loads(line) for line in args.run.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = {c.id: c for c in CASES}
    case_rows = {r["id"]: r for r in rows}
    missing = [c for c in cases if c not in case_rows]
    if missing:
        print(f"WARNING: {len(missing)} cases not run yet: {missing[:8]}")
    judge = NliJudge()
    scores = [score_case(cases[r["id"]], r, judge) for r in rows]
    metrics = aggregate(scores)
    metrics["by_tag_correctness"] = by_tag(scores, cases)
    metrics["failures"] = failure_breakdown(case_rows, cases)
    latency = [r["seconds"] for r in rows if r["llm_calls"]]
    metrics["operations"] = {
        "model": rows[0]["model"] if rows else "", "cases_run": len(rows), "model_calls": sum(r["llm_calls"] for r in rows),
        "mean_seconds_when_model_called": round(sum(latency) / len(latency), 1) if latency else None,
        "max_prompt_tokens": max((r["prompt_tokens"] for r in rows), default=0),
        "context_window": rows[0]["context_window"] if rows else None,
        "near_window_warnings": sum(any("NEAR CONTEXT WINDOW" in w for w in r["warnings"]) for r in rows),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / f"metrics_{args.tag}.json").write_text(json.dumps(metrics, indent=1, default=str), encoding="utf-8")
    table = [dataclasses.asdict(s) for s in scores]
    (args.out_dir / f"cases_{args.tag}.json").write_text(json.dumps(table, indent=1, default=str), encoding="utf-8")

    rng = random.Random(7)  # manual-audit sample: stratified by kind
    sample: list[dict[str, Any]] = []
    for kind, n in (("answerable", 16), ("out_of_domain", 4), ("near_miss", 4), ("false_premise", 2), ("injection", 3)):
        pool = [r for r in rows if r["kind"] == kind]
        sample.extend(rng.sample(pool, min(n, len(pool))))
    (args.out_dir / f"audit_sample_{args.tag}.json").write_text(
        json.dumps([{"id": r["id"], "kind": r["kind"], "query": r["query"], "refused": r["refused"], "reason": r["refusal_reason"],
                     "answer": r["text"], "cited": [c["citation_label"] for c in r["citations"]],
                     "sources": [s["text"][:700] for s in r["sources"]][:4]} for r in sample], indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(json.dumps(metrics, indent=1, default=str))


def main() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="stage", required=True)
    r = sub.add_parser("retrieve")
    r.add_argument("--index-dir", type=Path, required=True)
    r.add_argument("--cache", type=Path, required=True)
    r.add_argument("--rebuild", action="store_true")
    a = sub.add_parser("answer")
    a.add_argument("--cache", type=Path, required=True)
    a.add_argument("--expect-cache-sha256", default="", help="refuse to run unless the cache file has this sha256")
    a.add_argument("--model", required=True)
    a.add_argument("--base-url", default="http://localhost:11434/v1")
    a.add_argument("--api-key-env", default="", help="hosted APIs: name of the env variable holding the key (never printed)")
    a.add_argument("--out", type=Path, required=True)
    a.add_argument("--window", type=int, default=8192, help="context window the server was configured with (0 = unknown)")
    a.add_argument("--timeout", type=float, default=900.0)
    a.add_argument("--max-retries", type=int, default=1)
    a.add_argument("--limit", type=int, default=0)
    a.add_argument("--policy", choices=LIVE_POLICIES, default="A", help="A = shipped default; C = partial grounding ablation")
    a.add_argument("--ablate-grounding", action="store_true", help="deprecated alias of --policy C")
    s = sub.add_parser("score")
    s.add_argument("--run", type=Path, required=True)
    s.add_argument("--tag", required=True)
    s.add_argument("--out-dir", type=Path, default=Path("evaluation/results"))
    p = sub.add_parser("replay")
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--expect-cache-sha256", default="")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--policy", choices=POLICIES, required=True, help="B1 is experimental and offline only")
    p.add_argument("--out", type=Path, required=True)
    t = sub.add_parser("label-template")
    t.add_argument("--run", type=Path, required=True)
    t.add_argument("--cases", type=Path, help="cases_TAG.json from `score`, to show the judge's verdict per sentence")
    t.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    stages = {"retrieve": stage_retrieve, "answer": stage_answer, "score": stage_score, "replay": stage_replay,
              "label-template": stage_label_template}
    stages[args.stage](args)


if __name__ == "__main__":
    main()

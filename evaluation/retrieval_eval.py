"""Measure retrieval strategies on the labelled queries and calibrate the relevance policy.

    python -m evaluation.index_builder                       # once (slow: embeds the corpus)
    python -m evaluation.retrieval_eval --strategy all       # compare strategies
    python -m evaluation.retrieval_eval --strategy rerank --calibrate

Strategies
    baseline  vector search only, bibliography chunks not demoted (the behaviour before E2E-10)
    refs      + bibliography chunks ranked after body text
    rerank    + cross-encoder reranking of the top candidates

Calibration uses a two-fold split (even / odd query ids): thresholds fitted on one half are scored on the other,
so the reported numbers are not just the fit. With ~85 queries the estimates are coarse; see the dataset docstring.
"""

from __future__ import annotations

import argparse
import itertools
import json
import logging
import os
import statistics
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from ai.embedding import BgeEmbedder
from ai.retrieval import RetrievalService
from ai.retrieval.assessment import level_for, lexical_coverage
from ai.retrieval.models import RetrievedChunk
from ai.retrieval.references import is_reference_section
from ai.retrieval.rerank import CrossEncoderReranker
from evaluation.index_builder import COURSE, USER, build_index, open_stores
from evaluation.retrieval_dataset import ALL, EvalQuery

K = 5
STRATEGIES = {
    "baseline": {"include_references": True, "rerank": False},
    "refs": {"include_references": None, "rerank": False},
    "rerank": {"include_references": None, "rerank": True},
}


def matches(query: EvalQuery, hit: RetrievedChunk) -> bool:
    if query.file.lower() not in hit.file_name.lower():
        return False
    if is_reference_section(hit.heading_path, hit.text) and not query.allow_references:
        return False
    text = hit.text.lower()
    path = " > ".join(hit.heading_path).lower()
    return any(c.lower() in text for c in query.contains) or (bool(query.heading) and query.heading.lower() in path)


@dataclass(slots=True)
class QueryResult:
    id: str
    kind: str
    query: str
    rank: int | None  # 1-based rank of the first correct hit within K, answerable only
    top_vector: float
    top_rerank: float | None
    margin: float
    coverage: float
    missing: list[str]
    top1_is_reference: bool
    top1: str


def run_strategy(svc: RetrievalService, queries: list[EvalQuery], options: dict) -> list[QueryResult]:
    out: list[QueryResult] = []
    for q in queries:
        result = svc.search(q.query, user_id=USER, course_id=COURSE, k=K, assess_relevance=False, **options)
        hits = result.hits
        rank = next((i + 1 for i, h in enumerate(hits) if matches(q, h)), None) if q.kind == "answerable" else None
        coverage, missing = lexical_coverage(q.query, hits[:3])
        out.append(
            QueryResult(
                id=q.id,
                kind=q.kind,
                query=q.query,
                rank=rank,
                top_vector=hits[0].score if hits else 0.0,
                top_rerank=hits[0].rerank_score if hits else None,
                margin=(hits[0].score - hits[1].score) if len(hits) > 1 else 0.0,
                coverage=coverage,
                missing=list(missing),
                top1_is_reference=bool(hits) and hits[0].is_reference,
                top1=hits[0].citation_label[:70] if hits else "",
            )
        )
    return out


def ranking_metrics(results: list[QueryResult]) -> dict[str, float]:
    ans = [r for r in results if r.kind == "answerable"]
    n = len(ans) or 1
    return {
        "queries": len(ans),
        "hit@1": sum(r.rank == 1 for r in ans) / n,
        "hit@3": sum(r.rank is not None and r.rank <= 3 for r in ans) / n,
        "hit@5": sum(r.rank is not None for r in ans) / n,
        "mrr@5": sum(1 / r.rank for r in ans if r.rank) / n,
        "top1_is_reference": sum(r.top1_is_reference for r in results if r.kind == "answerable"),
    }


# ----------------------------------------------------------------------------- calibration
def level(r: QueryResult, strong: float, weak: float, min_coverage: float, use_rerank: bool) -> str:
    signal = r.top_rerank if use_rerank and r.top_rerank is not None else r.top_vector
    return level_for(signal, strong, weak, r.coverage, min_coverage)


def policy_metrics(results: list[QueryResult], strong: float, weak: float, cov: float, use_rerank: bool) -> dict[str, float]:
    levels = {r.id: level(r, strong, weak, cov, use_rerank) for r in results}
    by = defaultdict(list)
    for r in results:
        by[r.kind].append(r)

    def share(kind: str, pred) -> float:
        group = by[kind]
        return sum(pred(r, levels[r.id]) for r in group) / len(group) if group else 0.0

    strong_all = [r for r in results if levels[r.id] == "strong"]
    strong_ok = [r for r in strong_all if r.kind == "answerable" and r.rank is not None and r.rank <= 3]
    return {
        "answerable_pass": share("answerable", lambda r, lv: lv != "none"),
        "answerable_strong": share("answerable", lambda r, lv: lv == "strong"),
        "ood_refused": share("out_of_domain", lambda r, lv: lv == "none"),
        "near_refused": share("near_miss", lambda r, lv: lv == "none"),
        "strong_precision": len(strong_ok) / len(strong_all) if strong_all else 1.0,
    }


def _grid(values: list[float], steps: int = 40) -> list[float]:
    lo, hi = min(values), max(values)
    return [lo + (hi - lo) * i / steps for i in range(steps + 1)]


def fit(results: list[QueryResult], use_rerank: bool, ood_target: float = 0.95, precision_target: float = 0.95) -> dict[str, float]:
    signals = [r.top_rerank if use_rerank and r.top_rerank is not None else r.top_vector for r in results]
    best_weak: tuple[float, float, float, float] | None = None
    for weak, cov in itertools.product(_grid(signals), (0.0, 0.34, 0.5, 0.67)):
        m = policy_metrics(results, weak + 1e9, weak, cov, use_rerank)  # strong disabled: weak is the accept threshold
        if m["ood_refused"] >= ood_target:
            key = (m["answerable_pass"], m["near_refused"], -cov, weak)
            if best_weak is None or key > (best_weak[0], best_weak[1], -best_weak[2], best_weak[3]):
                best_weak = (key[0], key[1], cov, weak)
    if best_weak is None:
        weak, cov = max(signals), 0.5
    else:
        _, _, cov, weak = best_weak
    best_strong = max(signals) + 1.0
    for strong in sorted(_grid(signals, 80)):
        if strong < weak:
            continue
        m = policy_metrics(results, strong, weak, cov, use_rerank)
        if m["strong_precision"] >= precision_target and m["answerable_strong"] > 0:
            best_strong = strong
            break
    return {"strong": best_strong, "weak": weak, "min_coverage": cov}


def calibrate(results: list[QueryResult], use_rerank: bool) -> dict:
    folds = {
        "even": [r for r in results if int(r.id[1:]) % 2 == 0],
        "odd": [r for r in results if int(r.id[1:]) % 2 == 1],
    }
    cross = {}
    for train, test in (("even", "odd"), ("odd", "even")):
        params = fit(folds[train], use_rerank)
        cross[f"fit_{train}->test_{test}"] = {
            "params": params,
            "test": policy_metrics(folds[test], params["strong"], params["weak"], params["min_coverage"], use_rerank),
        }
    final = fit(results, use_rerank)
    return {
        "final_params": final,
        "on_all_data": policy_metrics(results, final["strong"], final["weak"], final["min_coverage"], use_rerank),
        "cross_validation": cross,
    }


def signal_summary(results: list[QueryResult], use_rerank: bool) -> dict[str, dict[str, float]]:
    out = {}
    for kind in ("answerable", "out_of_domain", "near_miss"):
        vals = [r.top_rerank if use_rerank and r.top_rerank is not None else r.top_vector for r in results if r.kind == kind]
        cov = [r.coverage for r in results if r.kind == kind]
        out[kind] = {
            "n": len(vals),
            "signal_min": min(vals),
            "signal_median": statistics.median(vals),
            "signal_max": max(vals),
            "coverage_median": statistics.median(cov),
        }
    return out


def assessment_report(svc: RetrievalService, queries: list[EvalQuery]) -> dict:
    """Run the real service with its shipped policy and count the levels it hands to the answer layer."""
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    rows = []
    for q in queries:
        result = svc.search(q.query, user_id=USER, course_id=COURSE, k=K)
        assessment = result.assessment
        assert assessment is not None
        counts[q.kind][assessment.level] += 1
        rows.append({"id": q.id, "kind": q.kind, "level": assessment.level, "missing": list(assessment.missing_terms)})
    return {"policy": svc.policy.version, "levels_by_kind": {k: dict(v) for k, v in counts.items()}, "rows": rows}


def main() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index-dir", type=Path, default=Path("evaluation/.index"))
    parser.add_argument("--strategy", choices=[*STRATEGIES, "all"], default="all")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--assess", action="store_true", help="also report the levels the shipped policy produces")
    parser.add_argument("--out", type=Path, default=Path("evaluation/results/retrieval_eval.json"))
    args = parser.parse_args()

    build_index(args.index_dir)
    store, parents = open_stores(args.index_dir)
    svc = RetrievalService(BgeEmbedder(), store, parent_store=parents, reranker=CrossEncoderReranker())
    names = list(STRATEGIES) if args.strategy == "all" else [args.strategy]
    report: dict = {"queries": len(ALL)}
    for name in names:
        started = time.time()
        results = run_strategy(svc, list(ALL), STRATEGIES[name])
        use_rerank = name == "rerank"
        entry = {
            "ranking": ranking_metrics(results),
            "signals": signal_summary(results, use_rerank),
            "seconds_per_query": round((time.time() - started) / len(ALL), 3),
            "results": [asdict(r) for r in results],
        }
        if args.calibrate:
            entry["calibration"] = calibrate(results, use_rerank)
        report[name] = entry
        print(f"\n== {name}  ({entry['seconds_per_query']}s/query)")
        print(" ranking:", {k: round(v, 3) for k, v in entry["ranking"].items()})
        print(" signals:", json.dumps({k: {a: round(b, 2) for a, b in v.items()} for k, v in entry["signals"].items()}))
        if args.calibrate:
            print(" calibration:", json.dumps(entry["calibration"], indent=1, default=lambda o: round(o, 3)))
    if args.assess:
        report["assessment"] = assessment_report(svc, list(ALL))
        print("\n== shipped policy", report["assessment"]["policy"])
        print(" levels by kind:", json.dumps(report["assessment"]["levels_by_kind"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("\nwritten", args.out)


if __name__ == "__main__":
    main()

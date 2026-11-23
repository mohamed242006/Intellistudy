"""Root-cause triage of every case that was not answered correctly (see docs/real_model_eval_report.md).

Usage:  python -m evaluation.root_cause --run RUN.jsonl --ablation ABLATION.jsonl --out evaluation/results/root_cause_TAG.json

Automatic first pass: it assigns the *primary* cause that the evidence supports and lists what remains for a human
reading. Categories:

    retrieval         relevance policy refused, or the gold source never reached the model
    missing_citation  the model produced content but left out [S#] tags, so the system dropped it or refused
    grounding_filter  sentences removed for low support / unmatched numbers (not for a missing tag)
    model_reasoning   gold source in context, no filter involved, model declined or answered wrongly/incompletely
    prompt            output violated the format in a way the prompt should have prevented (placeholder answers)
    judge             the instrument (gold matcher / NLI) is the likely culprit, not the system

``recoverable`` says whether the same model with the grounding checks switched off answered the case correctly, i.e.
whether the loss is attributable to the filter rather than to the model.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from evaluation.answer_gold import CASES, normalize
from evaluation.answer_metrics import score_facts, source_is_gold

PLACEHOLDER = re.compile(r"^(this|that|it) (is|are) (stated|mentioned|described|explained) in\b", re.IGNORECASE)


def load(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    return {r["id"]: r for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())}


def _strip_tags(text: str) -> str:
    return re.sub(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", "", text).strip()


def has_gold(case, row) -> bool:
    return any(source_is_gold(case, h["file_name"], h["citation_label"], h["text"]) for h in row["retrieved"])


def classify(case, row: dict[str, Any], abl: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return None for a case that is not a failure, else a record with the primary cause."""
    gold_in_context = has_gold(case, row)
    abl_correct = abl is not None and not abl["refused"] and score_facts(case, abl["text"]).correct
    reasons = [r[1] for r in row["grounding_removed_detail"]]
    record: dict[str, Any] = {
        "id": case.id, "kind": case.kind, "query": case.query, "gold_in_context": gold_in_context,
        "refusal_reason": row["refusal_reason"], "removed": len(reasons),
        "removed_reasons": dict(Counter("no citation" if r == "no citation" else "support/number" for r in reasons)),
        "recoverable_without_grounding": abl_correct if abl else None, "answer": row["text"][:400],
    }
    if case.expect == "answer":
        if not row["refused"] and score_facts(case, row["text"]).correct:
            return None
        if row["refused"] and row["refusal_reason"] in ("no_results", "not_relevant"):
            record["cause"] = "retrieval"
            record["detail"] = "relevance policy refused" + ("" if gold_in_context else "; gold source not retrieved")
        elif not gold_in_context:
            record["cause"] = "retrieval"
            record["detail"] = "gold source not in retrieved context"
        elif row["refused"] and row["refusal_reason"] == "uncited_answer":
            record["cause"] = "missing_citation"
            record["detail"] = "model answered without [S#] tags; answer refused after repair"
        elif row["refused"]:
            record["cause"] = "model_reasoning"
            record["detail"] = "model declined although the gold source was in context"
        elif PLACEHOLDER.match(_strip_tags(row["text"])) or len(_strip_tags(row["text"])) < 25:
            record["cause"] = "prompt"
            record["detail"] = "placeholder answer instead of content"
        elif reasons and abl_correct:
            record["cause"] = "missing_citation" if all(r == "no citation" for r in reasons) else "grounding_filter"
            record["detail"] = "sentences removed; the unfiltered answer is correct"
        elif reasons:
            record["cause"] = "model_reasoning"
            record["detail"] = "sentences removed, but the unfiltered answer is still not correct"
        else:
            record["cause"] = "model_reasoning"
            record["detail"] = "no filter involved; answer lacks required facts (human review needed)"
        return record
    if not row["refused"]:  # answered when a refusal was expected
        record["cause"] = "model_reasoning"
        record["detail"] = "answered a refuse-expected case (human review: may be a gold-label issue)"
        return record
    return None


def judge_disagreements(cases: list[dict[str, Any]], rows: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Sentences the NLI judge called unsupported although (nearly) all their content words are in the sources."""
    out = []
    for case in cases:
        row = rows[case["id"]]
        pool = normalize(" ".join(s["text"] for s in row["sources"]))
        for sentence in case.get("unsupported") or []:
            words = [w for w in normalize(sentence).split() if len(w) > 3]
            if not words:
                continue
            overlap = sum(f" {w}" in pool for w in words) / len(words)
            out.append({"id": case["id"], "sentence": sentence, "content_word_overlap": round(overlap, 2),
                        "verdict": "judge_disagreement" if overlap >= 0.8 else "possibly_unsupported"})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--ablation", type=Path)
    parser.add_argument("--cases", type=Path, help="cases_TAG.json from the score stage (for the judge-disagreement check)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    rows, abl = load(args.run), load(args.ablation)
    records = [r for c in CASES if c.id in rows and (r := classify(c, rows[c.id], abl.get(c.id))) is not None]
    summary = Counter(r["cause"] for r in records)
    recoverable = Counter(r["cause"] for r in records if r["recoverable_without_grounding"])
    result: dict[str, Any] = {"failures": len(records), "by_cause": dict(summary), "recoverable_by_cause": dict(recoverable),
                              "ablation_available": bool(abl), "records": records}
    if args.cases:
        scored = json.loads(args.cases.read_text(encoding="utf-8"))
        checks = judge_disagreements(scored, rows)
        result["judge_checks"] = {"unsupported_sentences": len(checks),
                                  "judge_disagreement": sum(c["verdict"] == "judge_disagreement" for c in checks),
                                  "possibly_unsupported": sum(c["verdict"] == "possibly_unsupported" for c in checks),
                                  "items": checks}
    args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("records", "judge_checks")}, indent=1))
    if "judge_checks" in result:
        print({k: v for k, v in result["judge_checks"].items() if k != "items"})


if __name__ == "__main__":
    main()

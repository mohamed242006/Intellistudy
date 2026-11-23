"""End-to-end check of the answer layer on the labelled queries (retrieval + reranker + policy + prompt + citations + grounding).

    python -m evaluation.answer_eval [--llm extractive|openai] [--model gpt-4o-mini] [--limit N]

By default the generator is ``ExtractiveLLM`` - a deterministic baseline that quotes source sentences. That means the
numbers below measure retrieval, refusal, citation and grounding machinery, **not the quality of a language model's
writing**. With ``--llm openai`` (needs OPENAI_API_KEY or --base-url for a local server) the same harness scores a real
model; none was available when this was written, so no real-model result exists yet.

Per query kind
    answerable   answered (not refused), and a cited source is the expected one (file + text / heading, as in
                 retrieval_eval); also counts answers whose grounding check removed sentences
    out_of_domain  refused (ideally before the model is called)
    near_miss    refused (reported separately: retrieval alone cannot always tell, the model / grounding must)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections import Counter
from pathlib import Path

from ai.answering import AnswerService, ExtractiveLLM, OpenAICompatibleClient
from ai.answering.models import Answer, SourceRef
from ai.embedding import BgeEmbedder
from ai.retrieval import RetrievalService
from ai.retrieval.rerank import CrossEncoderReranker
from evaluation.index_builder import COURSE, USER, build_index, open_stores
from evaluation.retrieval_dataset import ALL, EvalQuery


def cites_expected(query: EvalQuery, answer: Answer) -> bool:
    def ok(source: SourceRef) -> bool:
        if query.file.lower() not in source.file_name.lower():
            return False
        text, label = source.text.lower(), source.citation_label.lower()
        return any(c.lower() in text for c in query.contains) or (bool(query.heading) and query.heading.lower() in label)

    return any(ok(c.source) for c in answer.citations)


def run(service: AnswerService, queries: list[EvalQuery]) -> dict:
    rows = []
    for q in queries:
        answer = service.answer(q.query, user_id=USER, course_id=COURSE)
        rows.append({
            "id": q.id, "kind": q.kind, "refused": answer.refused, "reason": answer.refusal_reason,
            "cites_expected": cites_expected(q, answer) if q.kind == "answerable" else None,
            "removed_sentences": len(answer.grounding.removed) if answer.grounding else 0,
            "llm_calls": answer.llm_calls, "seconds": round(answer.seconds, 2), "confidence": answer.confidence,
            "answer": answer.text[:140],
        })
    by = {k: [r for r in rows if r["kind"] == k] for k in ("answerable", "out_of_domain", "near_miss")}
    ans = by["answerable"]
    answered = [r for r in ans if not r["refused"]]
    summary = {
        "queries": len(rows),
        "answerable": {
            "n": len(ans), "answered": len(answered),
            "answered_rate": round(len(answered) / len(ans), 3),
            "cites_expected_source": sum(bool(r["cites_expected"]) for r in answered),
            "cites_expected_rate_of_answered": round(sum(bool(r["cites_expected"]) for r in answered) / max(len(answered), 1), 3),
            "cites_expected_rate_of_all": round(sum(bool(r["cites_expected"]) for r in ans) / len(ans), 3),
            "refusal_reasons": dict(Counter(r["reason"] for r in ans if r["refused"])),
        },
        "out_of_domain": {"n": len(by["out_of_domain"]), "refused": sum(r["refused"] for r in by["out_of_domain"]),
                          "refused_without_model_call": sum(r["refused"] and r["llm_calls"] == 0 for r in by["out_of_domain"])},
        "near_miss": {"n": len(by["near_miss"]), "refused": sum(r["refused"] for r in by["near_miss"]),
                      "reasons": dict(Counter(r["reason"] for r in by["near_miss"] if r["refused"]))},
        "sentences_removed_by_grounding": sum(r["removed_sentences"] for r in rows),
        "mean_seconds": round(sum(r["seconds"] for r in rows) / len(rows), 2),
        "mean_llm_calls": round(sum(r["llm_calls"] for r in rows) / len(rows), 2),
    }
    return {"summary": summary, "rows": rows}


def main() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index-dir", type=Path, default=Path("evaluation/.index"))
    parser.add_argument("--llm", choices=("extractive", "openai"), default="extractive")
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--base-url", default="https://api.openai.com/v1")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--rebuild", action="store_true", help="rebuild the index first, in this same process")
    parser.add_argument("--out", type=Path, default=Path("evaluation/results/answer_eval.json"))
    args = parser.parse_args()

    build_index(args.index_dir, force=args.rebuild)
    store, parents = open_stores(args.index_dir)
    retrieval = RetrievalService(BgeEmbedder(), store, parent_store=parents, reranker=CrossEncoderReranker())
    llm = ExtractiveLLM() if args.llm == "extractive" else OpenAICompatibleClient(args.model, base_url=args.base_url)
    queries = list(ALL)[: args.limit] if args.limit else list(ALL)
    report = run(AnswerService(retrieval, llm), queries)
    report["generator"] = llm.model_name
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({"generator": llm.model_name, **report["summary"]}, indent=1))


if __name__ == "__main__":
    main()

"""Figure detection + selection against the hand labels in ``real_annotations.json``.

    python -m evaluation.figure_benchmark.detection_eval [--config key=value ...] [--show-errors]

For every annotated candidate the selector's decision is compared with the label:

    precision  of "keep"  - how many kept figures are really figures
    recall     of "keep"  - how many real figures are kept
    missed     labelled keepers for which no candidate was detected at all (detection recall)

PDF candidates are matched by page and bounding-box overlap, PPTX pictures by slide and picture index.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from ai.ingestion.figure_selection import SelectionConfig
from ai.ingestion.ingestion_pipeline import IngestionPipeline

ANNOTATIONS = Path(__file__).with_name("real_annotations.json")


def iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def evaluate(config: SelectionConfig, show_errors: bool = False) -> dict:
    data = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))
    pipeline = IngestionPipeline(figure_config=config)
    by_file: dict[str, list[dict]] = defaultdict(list)
    for a in data["annotations"]:
        by_file[a["file"]].append({**a, "slide": a["page"]})
    pptx: dict[str, list[dict]] = defaultdict(list)
    for a in data["pptx_annotations"]:
        pptx[a["file"]].append(a)

    rows: list[dict] = []
    for file, items in {**by_file, **pptx}.items():
        document = pipeline.ingest(file)
        decisions = document.metadata.get("figures", {}).get("decisions", [])
        is_pdf = file.endswith(".pdf")
        for item in items:
            if is_pdf:
                matches = [d for d in decisions if d["page"] == item["page"] and d["bbox"] and iou(d["bbox"], item["bbox"]) >= 0.3]
                best = max(matches, key=lambda d: iou(d["bbox"], item["bbox"]), default=None)
            else:
                best = next((d for d in decisions if d["page"] == item["slide"] and d["image_index"] == item["k"]), None)
            rows.append({"file": Path(file).name[:34], "where": item.get("page", item.get("slide")), "label": item["label"],
                         "detected": best is not None, "keep": bool(best and best["keep"]), "score": best["score"] if best else None,
                         "reasons": best["reasons"] if best else [], "features": best.get("features", {}) if best else {}, "caption": bool(best and best["label"]), "note": item.get("note", ""), "kind": "pdf" if is_pdf else "pptx"})

    def metrics(selected: list[dict]) -> dict:
        tp = sum(r["label"] == "keep" and r["keep"] for r in selected)
        fp = sum(r["label"] == "skip" and r["keep"] for r in selected)
        fn = sum(r["label"] == "keep" and not r["keep"] for r in selected)
        missed = sum(r["label"] == "keep" and not r["detected"] for r in selected)
        total_keep = sum(r["label"] == "keep" for r in selected)
        return {
            "annotated": len(selected), "keepers": total_keep, "tp": tp, "fp": fp, "fn": fn, "undetected_keepers": missed,
            "precision": round(tp / (tp + fp), 3) if tp + fp else 1.0,
            "recall": round(tp / total_keep, 3) if total_keep else 1.0,
        }

    out = {"all": metrics(rows), "pdf": metrics([r for r in rows if r["kind"] == "pdf"]), "pptx": metrics([r for r in rows if r["kind"] == "pptx"])}
    out["rows"] = rows
    if show_errors:
        out["errors"] = [r for r in rows if (r["label"] == "keep") != r["keep"]]
    return out


def main() -> None:
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", nargs="*", default=[], help="override SelectionConfig fields, e.g. keep_threshold=0.3")
    parser.add_argument("--show-errors", action="store_true")
    parser.add_argument("--dump", type=Path, help="write every annotated row with its features to this JSON file")
    args = parser.parse_args()
    overrides = {}
    for pair in args.config:
        key, value = pair.split("=")
        field = next(f for f in dataclasses.fields(SelectionConfig) if f.name == key)
        overrides[key] = (int if field.type in ("int", int) else float)(value)
    result = evaluate(SelectionConfig(**overrides), args.show_errors)
    if args.dump:
        args.dump.write_text(json.dumps(result["rows"], indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("errors", "rows")}, indent=1))
    for r in result.get("errors", []):
        print(f"  {'FN' if r['label'] == 'keep' else 'FP'} {r['file']} {r['where']} detected={r['detected']} score={r['score']} {r['reasons'][:3]} {r['note']}", file=sys.stdout)


if __name__ == "__main__":
    main()

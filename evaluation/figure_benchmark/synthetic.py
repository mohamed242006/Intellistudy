"""Synthetic figure corpus with exact ground truth.

Six small "papers" (PDF) are generated, each with two charts of *known data* - one embedded as a raster image, one as
vector graphics - a caption under every chart, a sentence in the body that cites it ("As shown in Figure 2, ..."),
distractor paragraphs that mention the same model names with other metrics, and negatives that must not become
figures: a logo on every page, a thin banner and a tiny icon.

    python -m evaluation.figure_benchmark.synthetic out_dir

Writes ``out_dir/*.pdf`` and ``out_dir/ground_truth.json``. Generation is deterministic.

Honest limit: the corpus is written by the same people who wrote the detector, so it measures whether the
mechanism works on clean inputs, not how it copes with the variety of real documents. The hand-labelled real files
(``real_annotations.json``) are the realistic half of the benchmark.
"""

from __future__ import annotations

import io
import json
import random
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pymupdf
from PIL import Image

PAPERS = [
    ("image_classification", "Image Classification", "validation accuracy", "training epochs", ["ResNet-50", "ViT-B", "EfficientNet", "ConvNeXt"], "%"),
    ("speech_recognition", "Speech Recognition", "word error rate", "noise level", ["Conformer", "Wav2Vec", "Whisper", "DeepSpeech"], "%"),
    ("machine_translation", "Machine Translation", "BLEU score", "sentence length", ["Transformer", "mBART", "NLLB", "ConvS2S"], ""),
    ("graph_learning", "Graph Neural Networks", "node classification accuracy", "number of layers", ["GCN", "GAT", "GraphSAGE", "GIN"], "%"),
    ("forecasting", "Time-Series Forecasting", "mean absolute error", "forecast horizon", ["Informer", "N-BEATS", "Prophet", "DeepAR"], ""),
    ("recommendation", "Recommender Systems", "recall at ten", "embedding size", ["NCF", "LightGCN", "SASRec", "BERT4Rec"], ""),
]
LOWER_IS_BETTER = {"word error rate", "mean absolute error"}


def _png_bytes(figure) -> bytes:
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png", dpi=110)
    plt.close(figure)
    return buffer.getvalue()


def _pdf_bytes(figure) -> bytes:
    buffer = io.BytesIO()
    figure.savefig(buffer, format="pdf")
    plt.close(figure)
    return buffer.getvalue()


def _chart(rng: random.Random, models: list[str], metric: str, axis: str, kind: str):
    """A bar chart (final values per model) or a line chart (value vs axis); returns (figure, winner, values)."""
    values = {m: round(rng.uniform(55, 95), 1) for m in models}
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    if kind == "bar":
        ax.bar(list(values), list(values.values()), color=["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"])
        ax.set_ylabel(metric)
    else:
        xs = list(range(1, 7))
        for model, final in values.items():
            ax.plot(xs, [final * (0.6 + 0.08 * i) for i in range(6)], marker="o", label=model)
        ax.set_xlabel(axis)
        ax.set_ylabel(metric)
        ax.legend(fontsize=7)
    ax.set_title(f"{metric.capitalize()}")
    ax.grid(alpha=0.3)
    best = (min if metric in LOWER_IS_BETTER else max)(values, key=values.get)  # type: ignore[arg-type]
    return fig, best, values


def _logo() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (160, 60), (30, 60, 140)).save(buffer, "PNG")
    return buffer.getvalue()


def _banner() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (900, 40), (200, 200, 200)).save(buffer, "PNG")
    return buffer.getvalue()


def _icon() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), (220, 120, 20)).save(buffer, "PNG")
    return buffer.getvalue()


def build(out: Path, limit: int | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(2026)
    truth: dict = {"papers": [], "questions": []}
    figure_number = 0
    for slug, topic, metric, axis, models, _unit in PAPERS[:limit]:
        doc = pymupdf.open()
        paper = {"file": f"{slug}.pdf", "topic": topic, "figures": [], "negatives": []}
        page_figures = [("bar", "raster"), ("line", "vector")]
        for page_no in range(1, 5):
            page = doc.new_page()
            page.insert_text((72, 60), f"{page_no}. {topic}: part {page_no}", fontsize=15)
            page.insert_image(pymupdf.Rect(480, 20, 560, 50), stream=_logo())  # logo on every page
            if page_no == 1:
                page.insert_image(pymupdf.Rect(40, 740, 570, 760), stream=_banner())
                page.insert_image(pymupdf.Rect(500, 80, 524, 104), stream=_icon())
                paper["negatives"] += [{"page": 1, "what": "banner"}, {"page": 1, "what": "icon"}]
            paper["negatives"].append({"page": page_no, "what": "logo"})
            intro = (
                f"This section of the {topic.lower()} study compares {', '.join(models[:-1])} and {models[-1]} on training time, "
                f"parameter count and robustness. {models[0]} and {models[1]} were also tuned for memory use. "
            )
            if page_no in (2, 3):
                kind, embed = page_figures[page_no - 2]
                figure_number += 1
                label_no = page_no - 1
                fig, best, values = _chart(rng, models, metric, axis, kind)
                a, b = models[0], models[1]
                cite = f"As shown in Figure {label_no}, {best} gives the best {metric} among all compared models."
                page.insert_textbox(pymupdf.Rect(72, 100, 540, 220), intro + cite, fontsize=11)
                rect = pymupdf.Rect(110, 240, 500, 240 + 390 * 3.2 / 5.2)
                if embed == "raster":
                    page.insert_image(rect, stream=_png_bytes(fig))
                else:
                    src = pymupdf.open("pdf", _pdf_bytes(fig))
                    page.show_pdf_page(rect, src, 0)
                caption = f"Figure {label_no}: {metric.capitalize()} of {a}, {b} and the other models {'versus ' + axis if kind == 'line' else 'on the benchmark'}."
                page.insert_textbox(pymupdf.Rect(110, 490, 500, 540), caption, fontsize=10)
                paper["figures"].append({"page": page_no, "label": f"Figure {label_no}", "embed": embed, "kind": kind, "caption": caption, "best": best, "metric": metric, "values": values})
                for question in (
                    f"How do {a} and {b} compare on {metric}?",
                    f"Which figure shows {metric} for {a} and {b}?",
                    f"What does the {metric} chart show for {a}?" if kind == "bar" else f"How does {metric} change with {axis}?",
                ):
                    truth["questions"].append({"q": question, "file": paper["file"], "label": f"Figure {label_no}", "caption": caption})
            else:
                page.insert_textbox(pymupdf.Rect(72, 100, 540, 300), intro + f"We report {metric} for each model in the following sections. " * 3, fontsize=11)
        doc.save(str(out / paper["file"]))
        doc.close()
        truth["papers"].append(paper)
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    return truth


if __name__ == "__main__":
    result = build(Path(sys.argv[1]))
    print(len(result["papers"]), "papers,", sum(len(p["figures"]) for p in result["papers"]), "figures,", len(result["questions"]), "questions")

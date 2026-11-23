"""Render every figure candidate of a PDF onto numbered contact sheets, for hand-labelling the benchmark.

    python -m evaluation.figure_benchmark.contact_sheets "data/uploads/1-Introduction ... .pdf" out_dir

Candidates are the raw output of detection *before* selection, so nothing the selector would skip is hidden.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from ai.ingestion.figures import detect_pdf_figures
from ai.ingestion.pdf_reader import PDFReader

THUMB = 300
COLS = 4


def candidates(path: Path) -> list[dict]:
    reader = PDFReader()
    out: list[dict] = []
    with pymupdf.open(path) as doc:
        for page in doc:
            images = reader.extract_images(page)
            for fig in detect_pdf_figures(page, images):
                out.append({
                    "id": len(out), "page": page.number + 1, "kind": fig.kind, "label": fig.label,
                    "caption": fig.caption[:90], "bbox": [round(v, 1) for v in fig.bbox] if fig.bbox else None,
                    "page_size": [round(page.rect.width, 1), round(page.rect.height, 1)],
                })
    return out


def render(path: Path, items: list[dict], out_dir: Path, per_sheet: int = 12) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    sheets: list[Path] = []
    with pymupdf.open(path) as doc:
        tiles: list[Image.Image] = []
        for item in items:
            page = doc[item["page"] - 1]
            clip = pymupdf.Rect(*item["bbox"]) if item["bbox"] else page.rect
            pix = page.get_pixmap(clip=pymupdf.Rect(clip.x0 - 4, clip.y0 - 4, clip.x1 + 4, clip.y1 + 4), dpi=90)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            img.thumbnail((THUMB, THUMB))
            tile = Image.new("RGB", (THUMB, THUMB + 22), "white")
            tile.paste(img, (0, 22))
            ImageDraw.Draw(tile).text((4, 4), f"#{item['id']} p{item['page']} {item['kind']} {item['label']}", fill="red")
            tiles.append(tile)
        for start in range(0, len(tiles), per_sheet):
            group = tiles[start : start + per_sheet]
            rows = (len(group) + COLS - 1) // COLS
            sheet = Image.new("RGB", (COLS * THUMB, rows * (THUMB + 22)), "white")
            for n, tile in enumerate(group):
                sheet.paste(tile, ((n % COLS) * THUMB, (n // COLS) * (THUMB + 22)))
            target = out_dir / f"{path.stem[:18].replace(' ', '_')}_sheet{start // per_sheet + 1}.png"
            sheet.save(target)
            sheets.append(target)
    return sheets


if __name__ == "__main__":
    pdf, out = Path(sys.argv[1]), Path(sys.argv[2])
    found = candidates(pdf)
    (out / f"{pdf.stem[:18].replace(' ', '_')}_candidates.json").parent.mkdir(parents=True, exist_ok=True)
    (out / f"{pdf.stem[:18].replace(' ', '_')}_candidates.json").write_text(json.dumps(found, indent=1), encoding="utf-8")
    print(len(found), "candidates;", [str(p) for p in render(pdf, found, out)])

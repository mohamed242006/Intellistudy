"""Contact sheets of the pictures of a PPTX, for hand-labelling the benchmark.

Pictures under 64 px on their short side are not listed: a hard rule rejects them and they are never figures.
Candidate id = (slide number, k-th picture of that slide in reading order), the same order the reader uses.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from pptx import Presentation
from pptx.shapes.picture import Picture

from ai.ingestion.pptx_reader import PptxReader

THUMB, COLS = 260, 5


def pictures(path: Path) -> list[dict]:
    reader = PptxReader.__new__(PptxReader)
    items: list[dict] = []
    for number, slide in enumerate(Presentation(str(path)).slides, start=1):
        k = 0
        for shape in reader._iter_shapes(slide.shapes):
            if not isinstance(shape, Picture):
                continue
            try:
                blob = shape.image.blob
                image = Image.open(io.BytesIO(blob))
                image.load()
            except Exception:
                k += 1
                continue
            if min(image.size) >= 64:
                items.append({"id": len(items), "slide": number, "k": k, "size": list(image.size), "alt": reader._alt_text(shape), "_img": image.convert("RGB")})
            k += 1
    return items


def main(pptx: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    items = pictures(pptx)
    stem = pptx.stem[:20].replace(" ", "_")
    listing = [{k: v for k, v in it.items() if k != "_img"} for it in items]
    (out / f"{stem}_pics.json").write_text(json.dumps(listing, indent=1), encoding="utf-8")
    for start in range(0, len(items), 20):
        group = items[start : start + 20]
        rows = (len(group) + COLS - 1) // COLS
        sheet = Image.new("RGB", (COLS * THUMB, rows * (THUMB + 18)), "white")
        for n, it in enumerate(group):
            im = it["_img"].copy()
            im.thumbnail((THUMB, THUMB))
            x, y = (n % COLS) * THUMB, (n // COLS) * (THUMB + 18)
            sheet.paste(im, (x, y + 18))
            ImageDraw.Draw(sheet).text((x + 3, y + 3), f"#{it['id']} s{it['slide']} {it['size'][0]}x{it['size'][1]}", fill="red")
        sheet.save(out / f"{stem}_sheet{start // 20 + 1}.png")
    print(pptx.name, len(items), "pictures")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))

"""Deterministic end-to-end fixtures (docs/F0B_GATE.md). Never uses data/uploads.

Writes into the directory given as the only argument:
  lecture-notes.pdf   valid text PDF                         -> ready
  lecture-slides.pptx valid PowerPoint with text             -> ready
  handout.docx        valid Word document with text          -> ready
  blank.pdf           valid PDF without any text             -> failed / no_text   (UI "Empty")
  damaged.pdf         PDF signature, unreadable body         -> failed / corrupted (UI "Failed", Retry)
  hostile.pdf         valid text PDF, uploaded under a hostile file name by the test
Uses python-docx and python-pptx from the backend's locked environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from pptx import Presentation
from pptx.util import Inches

SENTENCES = (
    "Queueing theory studies waiting lines. Little's Law states that the average number of customers in a stable "
    "system equals the arrival rate multiplied by the average time a customer spends in the system. "
)


def pdf(lines: list[str]) -> bytes:
    """A one-page PDF 1.4 with Helvetica text; byte offsets computed so the xref table is exact."""
    stream = "BT /F1 11 Tf 72 720 Td 14 TL " + " ".join(f"({line}) '" for line in lines) + " ET" if lines else ""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def wrap(text: str, width: int = 80) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return [*lines, line] if line else lines


def main(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "lecture-notes.pdf").write_bytes(pdf(wrap("Lecture notes. " + SENTENCES * 6)))
    (target / "hostile.pdf").write_bytes(pdf(wrap("Hostile name fixture. " + SENTENCES * 4)))
    (target / "blank.pdf").write_bytes(pdf([]))
    (target / "damaged.pdf").write_bytes(b"%PDF-1.4\n" + bytes(range(256)) * 64)

    deck = Presentation()
    for index in range(1, 4):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = f"Slide {index}: queueing networks"
        slide.placeholders[1].text = SENTENCES * 2
    deck.slides[0].shapes.add_textbox(Inches(1), Inches(6), Inches(6), Inches(1)).text = "Deterministic fixture"
    deck.save(target / "lecture-slides.pptx")

    doc = Document()
    doc.add_heading("Handout: queueing theory", level=1)
    for _ in range(4):
        doc.add_paragraph(SENTENCES * 2)
    doc.save(target / "handout.docx")


if __name__ == "__main__":
    main(Path(sys.argv[1]))

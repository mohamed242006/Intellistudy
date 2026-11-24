"""Generated test documents for M2 (valid and malicious). Nothing binary is committed: every file is built here."""

from __future__ import annotations

import io
import struct
import zipfile
import zlib

import pymupdf as fitz
from docx import Document as DocxDocument
from pptx import Presentation
from pptx.util import Inches

TEXT = ("Aspect-oriented programming separates cross-cutting concerns such as logging and security. "
        "A join point is a point in the execution of a program where an aspect can be applied. ") * 3


def pdf_bytes(pages: int = 2, *, user_password: str = "", owner_password: str = "", text: str = TEXT) -> bytes:
    document = fitz.open()
    for number in range(pages):
        page = document.new_page()
        page.insert_textbox(fitz.Rect(50, 50, 550, 800), f"Section {number + 1}\n{text}", fontsize=11)
    kwargs: dict[str, object] = {}
    if user_password or owner_password:
        kwargs = {"encryption": fitz.PDF_ENCRYPT_AES_256, "user_pw": user_password,  # type: ignore[attr-defined]
                  "owner_pw": owner_password or "o"}
    data = document.tobytes(**kwargs)
    document.close()
    return bytes(data)


def docx_bytes(paragraphs: int = 3) -> bytes:
    document = DocxDocument()
    document.add_heading("Aspect-Oriented Programming", level=1)
    for _ in range(paragraphs):
        document.add_paragraph(TEXT)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def small_png() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def pptx_with_bomb_image() -> bytes:
    """A deck whose picture is swapped, at the ZIP level, for a PNG declaring 900 million pixels."""
    deck = pptx_bytes(image=small_png())
    media = [n for n in zipfile.ZipFile(io.BytesIO(deck)).namelist() if n.startswith("ppt/media/")]
    return rezip(deck, replace={media[0]: bomb_png()})


def pptx_bytes(slides: int = 2, *, image: bytes | None = None) -> bytes:
    deck = Presentation()
    for number in range(slides):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = f"Slide {number + 1}: Join points"
        slide.placeholders[1].text = TEXT
        if image is not None and number == 0:
            slide.shapes.add_picture(io.BytesIO(image), Inches(1), Inches(1), Inches(2), Inches(2))
    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def rezip(original: bytes, *, add: dict[str, bytes] | None = None, replace: dict[str, bytes] | None = None,
          compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    """Copy an OOXML package, adding or replacing entries."""
    source = zipfile.ZipFile(io.BytesIO(original))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as target:
        for info in source.infolist():
            data = (replace or {}).get(info.filename, source.read(info))
            target.writestr(info.filename, data)
        for name, data in (add or {}).items():
            target.writestr(name, data)
    return buffer.getvalue()


def zip_bomb_docx(expanded_bytes: int = 20 * 1024 * 1024) -> bytes:
    """A valid DOCX plus one entry of zeros (compression ratio far above 100)."""
    return rezip(docx_bytes(), add={"word/media/zeros.bin": bytes(expanded_bytes)})


def many_entries_docx(entries: int) -> bytes:
    return rezip(docx_bytes(), add={f"word/extra/item{i}.xml": b"<x/>" for i in range(entries)})


def traversal_docx() -> bytes:
    return rezip(docx_bytes(), add={"../../evil.txt": b"x"})


def macro_docx() -> bytes:
    return rezip(docx_bytes(), add={"word/vbaProject.bin": b"\x00" * 64})


def overlapping_zip_docx() -> bytes:
    """Two central-directory entries pointing at the same local file data (the 'overlapping files' ZIP bomb)."""
    base = docx_bytes()
    source = zipfile.ZipFile(io.BytesIO(base))
    out = io.BytesIO()
    entries = []
    for info in source.infolist():
        data = source.read(info)
        compressed = zlib.compress(data)[2:-4]  # raw deflate
        offset = out.tell()
        name = info.filename.encode()
        crc = zlib.crc32(data)
        out.write(struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, 0, 0, crc, len(compressed), len(data), len(name), 0))
        out.write(name)
        out.write(compressed)
        entries.append((name, offset, crc, len(compressed), len(data)))
    # a second name pointing at the data of the first entry
    first = entries[0]
    entries.append((b"word/overlap.xml", first[1], first[2], first[3], first[4]))
    central_start = out.tell()
    for name, offset, crc, csize, usize in entries:
        out.write(struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 8, 0, 0, crc, csize, usize, len(name),
                              0, 0, 0, 0, 0, offset))
        out.write(name)
    central_size = out.tell() - central_start
    out.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries), central_size, central_start, 0))
    return out.getvalue()


def ole_bytes(*, encrypted: bool) -> bytes:
    """An OLE2 container: with an ``EncryptedPackage`` stream name (encrypted OOXML) or without (legacy .doc)."""
    header = bytes.fromhex("D0CF11E0A1B11AE1") + bytes(504)
    directory = ("EncryptedPackage" if encrypted else "WordDocument").encode("utf-16-le") + bytes(64)
    return header + directory + bytes(4096)


def bomb_png(width: int = 30_000, height: int = 30_000) -> bytes:
    """A tiny PNG whose header claims ``width`` x ``height`` pixels (above Pillow's decompression-bomb limit)."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 1, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00" * 64)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

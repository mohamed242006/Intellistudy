"""Structural checks on an uploaded file before any parser touches it (contract UPL-04..07, UPL-09).

Pure functions over a path, returning a reason code ("" when acceptable). They run inside the sandboxed child, and are
also unit-tested directly. Codes are the fixed, client-safe set of UPL-13.
"""

from __future__ import annotations

import itertools
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Fixed failure codes (UPL-13). The API maps each to a sentence; nothing else reaches clients.
UNSUPPORTED = "unsupported_type"
TYPE_MISMATCH = "type_mismatch"
PASSWORD_PROTECTED = "password_protected"
MACRO_DOCUMENT = "macro_document"
ARCHIVE_REJECTED = "archive_rejected"  # ZIP bomb, traversal names, overlapping entries, too many entries
TOO_MANY_PAGES = "too_many_pages"
CORRUPTED = "corrupted"

_MAIN_PARTS = {"docx": "word/document.xml", "pptx": "ppt/presentation.xml"}
_MAIN_TYPES = {
    "docx": b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
    "pptx": b"application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
}
_MACRO_TYPES = (b"macroEnabled", b"vnd.ms-office.vbaProject")
_SLIDE = re.compile(r"^ppt/slides/slide\d+\.xml$")
_ENCRYPTED_PACKAGE = "EncryptedPackage".encode("utf-16-le")
_LOCAL_HEADER = 30


@dataclass(frozen=True, slots=True)
class ZipLimits:
    max_uncompressed: int = 500 * 1024 * 1024
    max_ratio: float = 100.0
    max_entries: int = 10_000


def _bad_name(name: str) -> bool:
    return (
        name.startswith(("/", "\\"))
        or "\\" in name
        or "\x00" in name
        or re.match(r"^[A-Za-z]:", name) is not None
        or any(part == ".." for part in name.split("/"))
    )


def inspect_ooxml(path: Path, kind: str, limits: ZipLimits, max_pages: int) -> str:
    """DOCX / PPTX container checks, reading only the ZIP directory and ``[Content_Types].xml``."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError, ValueError):
        return CORRUPTED
    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_entries:
            return ARCHIVE_REJECTED
        names = [i.filename for i in infos]
        if len(set(names)) != len(names) or any(_bad_name(n) for n in names):
            return ARCHIVE_REJECTED
        if any(i.flag_bits & 0x1 for i in infos):
            return PASSWORD_PROTECTED  # ZIP-level encryption
        if sum(i.file_size for i in infos) > limits.max_uncompressed:
            return ARCHIVE_REJECTED
        for info in infos:
            if info.file_size and (info.compress_size == 0 or info.file_size / info.compress_size > limits.max_ratio):
                return ARCHIVE_REJECTED
        # entries whose data overlap (the "overlapping files" ZIP bomb) are rejected
        spans = sorted((i.header_offset, i.header_offset + _LOCAL_HEADER + len(i.filename) + i.compress_size)
                       for i in infos)
        if any(nxt[0] < cur[1] for cur, nxt in itertools.pairwise(spans)):
            return ARCHIVE_REJECTED
        if any(n.lower().endswith("vbaproject.bin") for n in names):
            return MACRO_DOCUMENT
        if "[Content_Types].xml" not in names or _MAIN_PARTS[kind] not in names:
            return TYPE_MISMATCH
        content_types = archive.getinfo("[Content_Types].xml")
        if content_types.file_size > 1024 * 1024:
            return ARCHIVE_REJECTED
        declared = archive.read(content_types)
        if any(marker in declared for marker in _MACRO_TYPES):
            return MACRO_DOCUMENT
        if _MAIN_TYPES[kind] not in declared:
            return TYPE_MISMATCH
        if kind == "pptx" and sum(1 for n in names if _SLIDE.match(n)) > max_pages:
            return TOO_MANY_PAGES
    return ""


def inspect_ole(path: Path) -> str:
    """An OLE2 file with a .docx/.pptx name: an encrypted OOXML package, or a legacy .doc/.ppt."""
    with path.open("rb") as handle:
        tail = b""
        while chunk := handle.read(1024 * 1024):
            if _ENCRYPTED_PACKAGE in tail + chunk:
                return PASSWORD_PROTECTED
            tail = chunk[-len(_ENCRYPTED_PACKAGE):]
    return UNSUPPORTED


def inspect_pdf(path: Path, max_pages: int) -> str:
    """Open without rendering: reject unreadable, password-protected or over-long PDFs.

    A PDF encrypted only with an owner password (permissions, no user password) opens without a password and is
    accepted: its content is readable and the encryption is not a protection boundary (finding F-M2-02).
    """
    import pymupdf as fitz  # imported here: only the sandbox opens documents

    try:
        document = fitz.open(path, filetype="pdf")
    except Exception:
        return CORRUPTED
    with document:
        if document.needs_pass:
            return PASSWORD_PROTECTED
        if document.page_count > max_pages:
            return TOO_MANY_PAGES
        if document.page_count == 0:
            return CORRUPTED
    return ""


def preflight(path: Path, kind: str, container: str, limits: ZipLimits, max_pages: int) -> str:
    """Dispatch on the verified container type (from magic bytes) and the declared kind (extension)."""
    if kind == "pdf":
        return inspect_pdf(path, max_pages) if container == "pdf" else TYPE_MISMATCH
    if kind in _MAIN_PARTS:
        if container == "ole":
            return inspect_ole(path)
        if container == "zip":
            return inspect_ooxml(path, kind, limits, max_pages)
        return TYPE_MISMATCH
    return UNSUPPORTED

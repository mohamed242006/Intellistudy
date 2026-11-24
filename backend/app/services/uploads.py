"""Streaming multipart reception (contract UPL-02, UPL-03, UPL-04, FILE-06).

The request body is parsed incrementally with python-multipart's callback parser. Every file part is written to its
own exclusive 0600 file in the storage's incoming area while bytes are counted and hashed; the request is aborted with
413 as soon as one file exceeds the per-file limit, so an oversized upload never lands on disk in full and is never
held in memory. Only a ``files`` field carrying a file name is accepted.

Type checks here are the cheap ones (extension + magic bytes); the structural checks (ZIP inspection, encryption,
page counts) run in the sandboxed parser (UPL-05..07, UPL-12).
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from python_multipart.multipart import MultipartParser, parse_options_header

from backend.app.core.errors import ApiError
from backend.app.services.storage import ALLOWED_EXTENSIONS, FileStorage, display_name, extension_of

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"
OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")  # legacy Office / encrypted OOXML container
HEAD_BYTES = 8


@dataclass(slots=True)
class IncomingFile:
    path: Path
    display_name: str
    extension: str
    size: int = 0
    head: bytes = b""
    container: str = ""  # pdf | zip | ole | "" (unknown)
    _sha: Any = field(default_factory=hashlib.sha256)

    @property
    def sha256(self) -> str:
        return str(self._sha.hexdigest())


@dataclass(slots=True)
class _Part:
    headers: dict[bytes, bytes] = field(default_factory=dict)
    file: IncomingFile | None = None
    handle: IO[bytes] | None = None


def container_of(head: bytes) -> str:
    if head.startswith(PDF_MAGIC):
        return "pdf"
    if head.startswith(ZIP_MAGIC):
        return "zip"
    if head.startswith(OLE_MAGIC):
        return "ole"
    return ""


def type_problem(item: IncomingFile) -> str:
    """Why a received file cannot be accepted ("" when the cheap checks pass)."""
    if item.size == 0:
        return "empty_file"
    if item.extension not in ALLOWED_EXTENSIONS:
        return "unsupported_type"  # includes .doc / .ppt / .docm / .pptm
    if item.extension == "pdf" and item.container != "pdf":
        return "type_mismatch"
    if item.extension in ("docx", "pptx") and item.container not in ("zip", "ole"):
        return "type_mismatch"  # OLE is passed on: encrypted OOXML vs legacy format is decided in the sandbox
    return ""


async def receive_files(
    content_type: str | None,
    body: AsyncIterator[bytes],
    storage: FileStorage,
    *,
    max_file_bytes: int,
    max_files: int,
) -> list[IncomingFile]:
    """Stream every file part to the incoming area. On any error every partial file is deleted."""
    media, params = parse_options_header((content_type or "").encode("latin-1"))
    boundary = params.get(b"boundary")
    if media != b"multipart/form-data" or not boundary:
        raise ApiError(415, "Upload files as multipart/form-data.", code="unsupported_media_type")

    received: list[IncomingFile] = []
    state: dict[str, Any] = {"part": None, "field": b"", "value": b"", "error": None}

    def fail(error: ApiError) -> None:
        if state["error"] is None:
            state["error"] = error

    def on_part_begin() -> None:
        state["part"] = _Part()

    def on_header_field(data: bytes, start: int, end: int) -> None:
        state["field"] += data[start:end]

    def on_header_value(data: bytes, start: int, end: int) -> None:
        state["value"] += data[start:end]

    def on_header_end() -> None:
        state["part"].headers[state["field"].lower()] = state["value"]
        state["field"], state["value"] = b"", b""

    def on_headers_finished() -> None:
        part: _Part = state["part"]
        disposition, options = parse_options_header(part.headers.get(b"content-disposition", b""))
        filename = options.get(b"filename")
        if disposition != b"form-data" or options.get(b"name") != b"files" or filename is None:
            fail(ApiError(422, "Only file parts named 'files' are accepted.", code="unexpected_field"))
            return
        if len(received) >= max_files:
            fail(ApiError(422, f"Upload at most {max_files} files at once.", code="too_many_files"))
            return
        name = display_name(filename.decode("utf-8", "replace"))
        item = IncomingFile(path=storage.new_incoming(), display_name=name, extension=extension_of(name))
        received.append(item)
        part.file = item
        part.handle = item.path.open("wb")

    def on_part_data(data: bytes, start: int, end: int) -> None:
        part: _Part = state["part"]
        if state["error"] is not None or part is None or part.handle is None or part.file is None:
            return
        chunk = data[start:end]
        item = part.file
        item.size += len(chunk)
        if item.size > max_file_bytes:
            fail(ApiError(413, "A file is larger than the upload limit.", code="file_too_large"))
            return
        if len(item.head) < HEAD_BYTES:
            item.head += chunk[: HEAD_BYTES - len(item.head)]
        item._sha.update(chunk)
        part.handle.write(chunk)

    def on_part_end() -> None:
        part: _Part = state["part"]
        if part is not None and part.handle is not None:
            part.handle.close()
            part.handle = None

    parser = MultipartParser(boundary, {
        "on_part_begin": on_part_begin, "on_header_field": on_header_field, "on_header_value": on_header_value,
        "on_header_end": on_header_end, "on_headers_finished": on_headers_finished, "on_part_data": on_part_data,
        "on_part_end": on_part_end,
    })
    try:
        async for chunk in body:
            parser.write(chunk)
            if state["error"] is not None:
                raise state["error"]
        parser.finalize()
        if state["error"] is not None:
            raise state["error"]
    except ApiError:
        _cleanup(storage, received, state)
        raise
    except Exception:  # malformed multipart from the client
        _cleanup(storage, received, state)
        raise ApiError(400, "The upload could not be read.", code="malformed_upload") from None
    if not received:
        raise ApiError(422, "No file was uploaded.", code="no_files")
    for item in received:
        item.container = container_of(item.head)
    return received


def _cleanup(storage: FileStorage, received: list[IncomingFile], state: dict[str, Any]) -> None:
    part = state.get("part")
    if part is not None and part.handle is not None:
        part.handle.close()
    for item in received:
        storage.discard(item.path)


def discard_all(storage: FileStorage, items: list[IncomingFile]) -> None:
    for item in items:
        storage.discard(item.path)

"""Ownership-safe file storage (contract FILE-01..08).

Layout: ``{root}/{owner_id}/{document_id}/original.{pdf|docx|pptx}``. Every component is server-generated and
validated; the client's file name is display metadata only. Every path is checked to resolve inside ``root`` before
it is opened, written or deleted (FILE-03). Directories are 0700, files 0600 (FILE-04).
"""

from __future__ import annotations

import os
import re
import shutil
import time
import unicodedata
import uuid
from pathlib import Path

from backend.app.services.ownership import is_canonical_id

ALLOWED_EXTENSIONS = ("pdf", "docx", "pptx")
_SEPARATORS = re.compile(r"[\\/]+")


class StorageError(Exception):
    """A path or storage invariant was violated. Never shown to clients."""


def display_name(raw: str | None, fallback: str = "document") -> str:
    """Client file name normalised for display (FILE-08): NFC, no control / format (bidi) characters, no path
    components, at most 255 characters with the extension preserved."""
    name = unicodedata.normalize("NFC", raw or "")
    name = _SEPARATORS.split(name)[-1]  # basename only, for both / and \
    name = "".join(ch for ch in name if unicodedata.category(ch) not in {"Cc", "Cf", "Cs", "Co", "Cn"})
    name = " ".join(name.split()).strip(" .")
    if not name:
        name = fallback
    if len(name) > 255:
        stem, dot, ext = name.rpartition(".")
        ext = ext[:16] if dot else ""
        name = (stem[: 255 - len(ext) - 1] + "." + ext) if ext else name[:255]
    return name


def extension_of(name: str) -> str:
    """Lower-case extension of a display name ("" when none)."""
    _, dot, ext = name.rpartition(".")
    return ext.lower() if dot else ""


class FileStorage:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.incoming = self.root / ".incoming"
        for directory in (self.root, self.incoming):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)

    # ---------------------------------------------------------------------------------------- paths
    def _inside(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise StorageError("path escapes the storage root")
        return resolved

    def document_dir(self, owner_id: str, document_id: str) -> Path:
        if not (is_canonical_id(owner_id) and is_canonical_id(document_id)):
            raise StorageError("owner and document ids must be canonical UUIDs")
        return self._inside(self.root / owner_id / document_id)

    def document_path(self, owner_id: str, document_id: str, file_type: str) -> Path:
        if file_type not in ALLOWED_EXTENSIONS:
            raise StorageError("unsupported stored file type")
        return self._inside(self.document_dir(owner_id, document_id) / f"original.{file_type}")

    # ------------------------------------------------------------------------------------ lifecycle
    def new_incoming(self) -> Path:
        """An exclusive, 0600 temporary file for one streamed upload (FILE-06)."""
        path = self._inside(self.incoming / f"{uuid.uuid4()}.part")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        return path

    def place(self, incoming: Path, owner_id: str, document_id: str, file_type: str) -> Path:
        """Atomically move a validated upload into its final location."""
        source = self._inside(incoming)
        if source.parent != self.incoming:
            raise StorageError("only files from the incoming area can be placed")
        target = self.document_path(owner_id, document_id, file_type)
        owner_dir = target.parent.parent
        owner_dir.mkdir(exist_ok=True, mode=0o700)
        target.parent.mkdir(exist_ok=False, mode=0o700)
        os.replace(source, target)
        os.chmod(target, 0o600)
        return target

    def discard(self, incoming: Path) -> None:
        path = self._inside(incoming)
        if path.parent == self.incoming:
            path.unlink(missing_ok=True)

    def delete_document(self, owner_id: str, document_id: str) -> None:
        directory = self.document_dir(owner_id, document_id)
        if directory.exists():
            shutil.rmtree(directory)

    def sweep_incoming(self, older_than_seconds: float = 3600) -> int:
        """Remove abandoned partial uploads (FILE-07)."""
        cutoff = time.time() - older_than_seconds
        removed = 0
        for path in self.incoming.glob("*.part"):
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        return removed

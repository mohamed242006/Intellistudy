"""Run the sandboxed parser and validate what it returns (contract UPL-12, FILE-09, VEC-01).

* The child gets an **allowlisted** environment: no ``INTELLISTUDY_*`` variable, no API key, no JWT secret, no
  database URL (FILE-09). Variables that look like secrets are dropped even if allowlisted.
* It runs in its own session so the whole process group (including Tesseract children) can be killed.
* A watchdog kills it on the wall-clock timeout, or when its **resident** memory (child plus descendants) exceeds the
  configured limit; ``RLIMIT_AS`` inside the child is only a coarse ceiling (finding F-M2-01).
* Its output is untrusted JSON: size-bounded, parsed without code execution, every chunk rebuilt from an exact field
  set and checked to carry the expected ``user_id``, ``course_id`` and ``document_uid`` (VEC-01, tripwire).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from ai.chunking.models import ChildChunk, ParentChunk
from backend.app.core.config import Settings
from backend.app.core.logging import security_event

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: Environment variables the child may inherit (FILE-09). Everything else is dropped.
ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TZ",
    "HF_HOME", "HF_HUB_CACHE", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "TRANSFORMERS_CACHE",
    "TESSDATA_PREFIX", "SYSTEMROOT",
})
_SECRET_LOOKING = re.compile(r"(?i)(secret|token|key|password|passwd|credential|auth|database_url|dsn)")

#: Fixed failure codes from the sandbox in addition to preflight's (UPL-13).
TIMED_OUT = "timed_out"
TOO_LARGE = "too_large"
UNREADABLE = "unreadable"
INVALID_OUTPUT = "invalid_output"

_TUPLE_FIELDS = ("heading_path", "section_titles", "block_orders", "block_types")
_MAX_CHUNKS = 200_000


@dataclass(slots=True)
class ParseOutcome:
    ok: bool
    error: str = ""
    page_count: int = 0
    children: list[ChildChunk] = field(default_factory=list)
    parents: list[ParentChunk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def child_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """The child's environment: allowlisted names only, never anything that looks like a secret (FILE-09)."""
    env = {k: v for k, v in (source if source is not None else os.environ).items()
           if k in ENV_ALLOWLIST and not _SECRET_LOOKING.search(k)}
    env.update({
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "PYTHONHASHSEED": "0",
    })
    return env


def _rss_bytes(pid: int) -> int:
    """Resident memory of ``pid`` and all its descendants (Linux /proc); 0 when unavailable."""
    total, stack = 0, [pid]
    while stack:
        current = stack.pop()
        try:
            for line in Path(f"/proc/{current}/status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1]) * 1024
                    break
            children = Path(f"/proc/{current}/task/{current}/children").read_text().split()
            stack.extend(int(c) for c in children)
        except (OSError, ValueError):
            continue
    return total


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=10)


CHILD_MODULE = "backend.app.worker.parse_child"


def run_parse(path: Path, *, kind: str, container: str, user_id: str, course_id: str, document_id: str,
              settings: Settings, work_root: Path, child_module: str = CHILD_MODULE) -> ParseOutcome:
    """Parse and chunk ``path`` in the sandbox; never raises for document problems.

    ``child_module`` exists for the sandbox tests (probe children that hang, exhaust memory or report their
    environment); production always runs :data:`CHILD_MODULE`.
    """
    path = Path(path).resolve()  # the child runs in its own working directory
    work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    work = Path(tempfile.mkdtemp(prefix="parse-", dir=work_root))
    try:
        output = work / "result.json"
        request = {
            "input": str(path), "output": str(output), "kind": kind, "container": container,
            "user_id": user_id, "course_id": course_id, "document_id": document_id,
            "max_pages": settings.max_pages, "tokenizer": settings.chunk_tokenizer,
            "zip_max_uncompressed": settings.zip_max_uncompressed_bytes, "zip_max_ratio": settings.zip_max_ratio,
            "zip_max_entries": settings.zip_max_entries, "ocr_timeout_seconds": settings.ocr_timeout_seconds,
            "address_space_bytes": settings.parse_address_space_bytes,
            "cpu_seconds": settings.parse_timeout_seconds + 30, "max_output_bytes": settings.parse_max_output_bytes,
        }
        stderr_path = work / "stderr.txt"
        with stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                [sys.executable, "-m", child_module, json.dumps(request)],
                cwd=str(work), env=child_environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=stderr, start_new_session=True,
            )
            outcome = _watch(process, settings)
        if outcome is not None:
            return outcome
        if process.returncode != 0:
            tail = stderr_path.read_bytes()[-2000:].decode("utf-8", "replace")
            logger.warning("parser child exited with %s: %s", process.returncode, tail[-500:])
            if process.returncode in (-signal.SIGKILL, -signal.SIGXCPU, 128 + signal.SIGKILL):
                return ParseOutcome(False, TIMED_OUT)
            return ParseOutcome(False, TOO_LARGE if "MemoryError" in tail else UNREADABLE)
        return _read_output(output, settings, user_id=user_id, course_id=course_id, document_id=document_id)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _watch(process: subprocess.Popen[bytes], settings: Settings) -> ParseOutcome | None:
    deadline = time.monotonic() + settings.parse_timeout_seconds
    while process.poll() is None:
        if time.monotonic() > deadline:
            _kill_group(process)
            security_event("parse_timeout", seconds=settings.parse_timeout_seconds)
            return ParseOutcome(False, TIMED_OUT)
        if _rss_bytes(process.pid) > settings.parse_rss_limit_bytes:
            _kill_group(process)
            security_event("parse_memory_limit", limit_bytes=settings.parse_rss_limit_bytes)
            return ParseOutcome(False, TOO_LARGE)
        time.sleep(0.1)
    return None


def _read_output(output: Path, settings: Settings, *, user_id: str, course_id: str, document_id: str) -> ParseOutcome:
    if not output.exists() or output.stat().st_size > settings.parse_max_output_bytes:
        return ParseOutcome(False, INVALID_OUTPUT if output.exists() else UNREADABLE)
    try:
        data = json.loads(output.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError):
        return ParseOutcome(False, INVALID_OUTPUT)
    if not isinstance(data, dict) or not isinstance(data.get("ok"), bool):
        return ParseOutcome(False, INVALID_OUTPUT)
    if not data["ok"]:
        error = data.get("error")
        return ParseOutcome(False, error if isinstance(error, str) and re.fullmatch(r"[a-z_]{1,32}", error)
                            else INVALID_OUTPUT)
    try:
        children = [_child_from_dict(c) for c in _bounded_list(data.get("children"))]
        parents = [_parent_from_dict(p) for p in _bounded_list(data.get("parents"))]
        page_count = int(data.get("page_count", 0))
        warnings = [str(w)[:300] for w in _bounded_list(data.get("warnings"))][:50]
    except (TypeError, ValueError, KeyError):
        return ParseOutcome(False, INVALID_OUTPUT)
    for chunk in (*children, *parents):
        if (chunk.user_id, chunk.course_id, chunk.document_uid) != (user_id, course_id, document_id):
            security_event("sandbox_scope_mismatch", document_id=document_id)  # tripwire: never expected
            return ParseOutcome(False, INVALID_OUTPUT)
    if not children:
        return ParseOutcome(False, "no_text")
    return ParseOutcome(True, page_count=page_count, children=children, parents=parents, warnings=warnings)


def _bounded_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > _MAX_CHUNKS:
        raise ValueError("expected a bounded list")
    return value


def _restore_tuples(values: dict[str, Any]) -> dict[str, Any]:
    for name in _TUPLE_FIELDS:
        values[name] = tuple(values[name])
    values["block_ranges"] = tuple((int(a), int(b)) for a, b in values["block_ranges"])
    values["bboxes"] = tuple((int(p), tuple(float(x) for x in box)) for p, box in values["bboxes"])
    return values


def _exact_fields(cls: type, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise TypeError("chunk must be an object")
    expected = {f.name for f in fields(cls)}
    if set(data) != expected:
        raise ValueError("unexpected chunk fields")
    for name in ("chunk_id", "text", "document_uid", "user_id", "course_id"):
        if not isinstance(data[name], str):
            raise TypeError(f"{name} must be a string")
    return dict(data)


def _child_from_dict(data: Any) -> ChildChunk:
    values = _restore_tuples(_exact_fields(ChildChunk, data))
    for name in ("embedding_text", "parent_id", "embedding_hash"):
        if not isinstance(values[name], str):
            raise TypeError(f"{name} must be a string")
    return ChildChunk(**values)


def _parent_from_dict(data: Any) -> ParentChunk:
    _exact_fields(ParentChunk, data)
    return ParentChunk.from_dict(data)

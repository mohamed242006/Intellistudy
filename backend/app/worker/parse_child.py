"""Sandboxed parser process (contract UPL-08, UPL-12, FILE-09).

    python -m backend.app.worker.parse_child '<json request>'

Runs in a separate process with resource limits set before any parser is imported, an allowlisted environment (no
secrets), and access only to the one file named in the request. It validates the file (preflight), ingests it, chunks
it, and writes **JSON** (never pickle) to the output path. The parent treats that JSON as untrusted (sandbox.py).

Exit code 0 means a result file was written (``ok`` true or false); anything else is a crash.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

MAX_WARNINGS = 50


def _apply_limits(request: dict[str, Any]) -> None:
    import resource

    address_space = int(request["address_space_bytes"])
    cpu = int(request["cpu_seconds"])
    resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    output_cap = int(request["max_output_bytes"]) + 1024 * 1024
    resource.setrlimit(resource.RLIMIT_FSIZE, (output_cap, output_cap))


def _harden_libraries(request: dict[str, Any]) -> None:
    import warnings

    from PIL import Image

    Image.MAX_IMAGE_PIXELS = 89_478_485  # UPL-08: explicit decompression-bomb threshold
    warnings.simplefilter("error", Image.DecompressionBombWarning)  # above the limit: skip the image, do not decode

    from ai.ingestion import ocr_processor

    ocr_processor.DEFAULT_TIMEOUT_SECONDS = float(request["ocr_timeout_seconds"])


def _result(ok: bool, **fields: Any) -> dict[str, Any]:
    return {"ok": ok, **fields}


def run(request: dict[str, Any]) -> dict[str, Any]:
    from backend.app.worker.preflight import CORRUPTED, TOO_MANY_PAGES, ZipLimits, preflight

    path = Path(request["input"])
    limits = ZipLimits(int(request["zip_max_uncompressed"]), float(request["zip_max_ratio"]),
                       int(request["zip_max_entries"]))
    problem = preflight(path, request["kind"], request["container"], limits, int(request["max_pages"]))
    if problem:
        return _result(False, error=problem)

    from ai.chunking import ChunkContext, ChunkingEngine
    from ai.chunking.config import EMBEDDING_MODEL
    from ai.chunking.tokens import ApproxTokenCounter, default_token_counter
    from ai.ingestion.ingestion_pipeline import IngestionPipeline
    from ai.ingestion.models import IngestionError

    try:
        document = IngestionPipeline().ingest(path)
    except MemoryError:
        return _result(False, error="too_large")
    except IngestionError as exc:
        return _result(False, error="password_protected" if "password" in str(exc).lower() else "unreadable")
    except Exception:
        return _result(False, error="unreadable")

    page_count = int(getattr(document.source, "page_count", 0) or 0)
    if page_count > int(request["max_pages"]):
        return _result(False, error=TOO_MANY_PAGES)
    if not document.pages:
        return _result(False, error=CORRUPTED)

    tokenizer = default_token_counter() if request["tokenizer"] == "hf" else ApproxTokenCounter()
    context = ChunkContext(request["user_id"], request["course_id"], request["document_id"], EMBEDDING_MODEL)
    try:
        chunks = ChunkingEngine(tokenizer=tokenizer).run(document, context)
    except MemoryError:
        return _result(False, error="too_large")
    except Exception:
        return _result(False, error="unreadable")

    warnings = [str(w)[:300] for page in document.pages for w in page.warnings][:MAX_WARNINGS]
    return _result(
        True,
        page_count=page_count,
        children=[asdict(c) for c in chunks.children],
        parents=[p.to_dict() for p in chunks.parents],
        warnings=warnings,
        problems=[str(p)[:300] for p in chunks.report.problems][:MAX_WARNINGS],
    )


def main(argv: list[str]) -> int:
    request = json.loads(argv[1])
    _apply_limits(request)
    _harden_libraries(request)
    import logging

    logging.disable(logging.WARNING)  # library warnings would only fill stderr
    result = run(request)
    output = Path(request["output"])
    tmp = output.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)
    os.replace(tmp, output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

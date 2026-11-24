"""Probe child processes for the sandbox tests (run as ``python -m backend.tests.sandbox_probes '<request>'``).

The behaviour is chosen by the content of the input file: ``hang`` sleeps forever, ``memory`` keeps allocating,
``env`` writes the names of its environment variables next to the input file, ``crash`` exits with an error, ``bad``
writes malformed output, ``scope`` writes chunks claiming another user's scope.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main(argv: list[str]) -> int:
    request = json.loads(argv[1])
    mode = Path(request["input"]).read_text().strip()
    output = Path(request["output"])
    if mode == "hang":
        while True:
            time.sleep(1)
    if mode == "memory":
        hoard = []
        while True:
            hoard.append(bytearray(50 * 1024 * 1024))
            time.sleep(0.02)
    if mode == "env":
        Path(request["input"]).with_suffix(".env.json").write_text(json.dumps(sorted(os.environ)))
        output.write_text(json.dumps({"ok": False, "error": "probe"}))
        return 0
    if mode == "crash":
        raise SystemExit(3)
    if mode == "bad":
        output.write_text("{not json")
        return 0
    if mode == "huge_error":
        output.write_text(json.dumps({"ok": False, "error": "<script>alert(1)</script> /etc/passwd"}))
        return 0
    output.write_text(json.dumps({"ok": False, "error": "unknown_probe"}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

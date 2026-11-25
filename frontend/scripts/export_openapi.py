"""Export the backend's OpenAPI schema without running a server (deterministic; used by `npm run api:schema`).

The app is built in-process from a temporary working directory, so the backend's `.env` (secrets, provider keys) is
never read: Settings resolve `.env` relative to the working directory, and every setting needed is given below.
Usage: python3 scripts/export_openapi.py <output.json>   (with the backend's Python environment active)
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main(argv: list[str]) -> int:
    output = Path(argv[1]).resolve() if len(argv) > 1 else Path("lib/api/openapi.json").resolve()
    start = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="intellistudy-openapi-") as tmp:
        os.chdir(tmp)
        os.environ.update({
            "INTELLISTUDY_PROFILE": "demo",
            "INTELLISTUDY_JWT_SECRET": secrets.token_urlsafe(32),  # throwaway: the schema does not depend on it
            "INTELLISTUDY_LLM_PROVIDER": "none",
            "INTELLISTUDY_DATABASE_URL": f"sqlite:///{tmp}/schema.sqlite3",
            "INTELLISTUDY_DATA_DIR": tmp,
            "INTELLISTUDY_STORAGE_ROOT": f"{tmp}/storage",
            "INTELLISTUDY_WORKER_ENABLED": "false",
        })
        sys.path.insert(0, str(REPO))
        from backend.app.main import create_app

        schema = create_app().openapi()
        os.chdir(start)
    output.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OpenAPI schema written to {output.relative_to(start) if output.is_relative_to(start) else output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

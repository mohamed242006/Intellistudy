"""Shared test fixtures. Secrets here are generated per run; none is a real credential."""

from __future__ import annotations

import secrets
import tempfile
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings

#: Strong-looking values generated at import time, so no fixed secret string lives in the repository.
JWT_SECRET = secrets.token_urlsafe(32)
DEEPSEEK_KEY = "sk-" + secrets.token_hex(16)


def make_settings(tmp: str | Path | None = None, **overrides: Any) -> Settings:
    """Settings isolated from the developer's environment and ``.env`` file."""
    base = Path(tmp or tempfile.mkdtemp(prefix="intellistudy-test-"))
    values: dict[str, Any] = {
        "profile": "test",
        "database_url": f"sqlite:///{base / 'test.sqlite3'}",
        "data_dir": base / "data",
        "storage_root": base / "storage",
        "llm_provider": "none",
        "jwt_secret": JWT_SECRET,
        # the contract's minimum Argon2id parameters (JWT-10): still real Argon2id, but fast enough for many logins
        "argon2_memory_kib": 19456,
        "argon2_time_cost": 2,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)

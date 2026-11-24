"""Apply migrations programmatically:  ``python -m backend.app.db.migrate [DATABASE_URL]``.

Without an argument the URL comes from ``INTELLISTUDY_DATABASE_URL`` (or the demo default). The service does not
migrate on startup; run this explicitly (demo setup script, deployment step).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

from backend.app.db.session import create_db_engine

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
DEFAULT_URL = "sqlite:///data/backend/intellistudy.sqlite3"


def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


def upgrade(database_url: str, revision: str = "head") -> None:
    engine = create_db_engine(database_url)
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
    finally:
        engine.dispose()


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else os.environ.get("INTELLISTUDY_DATABASE_URL", DEFAULT_URL)
    upgrade(url)
    print("database is at the latest revision")  # the URL is not printed: it may contain credentials
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

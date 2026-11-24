"""Alembic environment. Works unchanged on SQLite (demo) and PostgreSQL (production)."""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import Connection

from backend.app.db import models  # noqa: F401  (registers every table on Base.metadata)
from backend.app.db.base import Base
from backend.app.db.session import create_db_engine

DEFAULT_URL = "sqlite:///data/backend/intellistudy.sqlite3"

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return context.get_x_argument(as_dictionary=True).get("url") or os.environ.get(
        "INTELLISTUDY_DATABASE_URL", DEFAULT_URL
    )


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        render_as_batch=True,  # ALTER TABLE support on SQLite; harmless on PostgreSQL
        compare_type=True,
        literal_binds=connection is None,
    )


def run_migrations_offline() -> None:
    _configure(url=_url())
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:  # programmatic use (tests, migrate.py) passes an open connection
        _configure(connection=connectable)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_db_engine(_url())
    with engine.connect() as connection:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

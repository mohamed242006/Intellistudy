"""Engine and session factory. One engine per process; sessions are short-lived (one per request or job step)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def create_db_engine(database_url: str, *, echo: bool = False) -> Engine:
    """Create the engine. SQLite gets WAL, foreign keys and a busy timeout; other back ends use their defaults."""
    url = make_url(database_url)
    kwargs: dict[str, Any] = {"echo": echo, "pool_pre_ping": True}
    if url.get_backend_name() == "sqlite":
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)
    if url.get_backend_name() == "sqlite":
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def _sqlite_pragmas(dbapi_connection: Any, _: Any) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")  # cascades and FK checks (ISO-03 relies on them)
        cursor.execute("PRAGMA journal_mode=WAL")  # readers do not block the single writer
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a session; roll back on error, always close. Used by the FastAPI dependency and by jobs."""
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

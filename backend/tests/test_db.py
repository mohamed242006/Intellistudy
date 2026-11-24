"""Database layer: migrations, portable types and SQLite settings (project decision: SQLite now, PostgreSQL later)."""

from __future__ import annotations

import shutil
import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import String, Table, inspect, select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Mapped, Session, mapped_column

from backend.app.db.base import Base, Timestamps, UTCDateTime, UUIDPrimaryKey, new_uuid
from backend.app.db.migrate import upgrade
from backend.app.db.session import create_db_engine


class _Probe(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "_test_probe"
    label: Mapped[str] = mapped_column(String(20))
    seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


PROBE_TABLE: Table = _Probe.__table__  # type: ignore[assignment]


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="intellistudy-db-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.url = f"sqlite:///{self.tmp}/nested/dir/db.sqlite3"

    def test_migrations_apply_on_a_fresh_database(self) -> None:
        upgrade(self.url)
        engine = create_db_engine(self.url)
        self.addCleanup(engine.dispose)
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        self.assertEqual(version, "0001_baseline")
        upgrade(self.url)  # idempotent

    def test_sqlite_pragmas(self) -> None:
        engine = create_db_engine(self.url)
        self.addCleanup(engine.dispose)
        with engine.connect() as conn:
            self.assertEqual(conn.execute(text("PRAGMA foreign_keys")).scalar_one(), 1)
            self.assertEqual(conn.execute(text("PRAGMA journal_mode")).scalar_one().lower(), "wal")

    def test_uuid_ids_and_utc_round_trip(self) -> None:
        engine = create_db_engine(self.url)
        self.addCleanup(engine.dispose)
        PROBE_TABLE.create(engine)
        cairo = timezone(timedelta(hours=2))
        with Session(engine) as session:
            probe = _Probe(label="x", seen_at=datetime(2026, 11, 24, 12, 0, tzinfo=cairo))
            session.add(probe)
            session.commit()
            probe_id = probe.id
        with Session(engine) as session:
            loaded = session.scalars(select(_Probe).where(_Probe.id == probe_id)).one()
            self.assertEqual(uuid.UUID(loaded.id).version, 4)
            assert loaded.seen_at is not None
            self.assertEqual(loaded.seen_at, datetime(2026, 11, 24, 10, 0, tzinfo=UTC))
            self.assertEqual(loaded.seen_at.tzinfo, UTC)
            self.assertEqual(loaded.created_at.tzinfo, UTC)

    def test_naive_datetimes_are_rejected(self) -> None:
        engine = create_db_engine(self.url)
        self.addCleanup(engine.dispose)
        PROBE_TABLE.create(engine)
        with Session(engine) as session:
            session.add(_Probe(label="x", seen_at=datetime(2026, 11, 24, 12, 0)))
            with self.assertRaises(StatementError):
                session.commit()

    def test_new_uuid_is_v4_and_unique(self) -> None:
        ids = {new_uuid() for _ in range(1000)}
        self.assertEqual(len(ids), 1000)
        self.assertTrue(all(uuid.UUID(i).version == 4 for i in ids))

    def test_naming_convention_is_applied(self) -> None:
        engine = create_db_engine(self.url)
        self.addCleanup(engine.dispose)
        PROBE_TABLE.create(engine)
        self.assertEqual(inspect(engine).get_pk_constraint("_test_probe")["name"], "pk__test_probe")


if __name__ == "__main__":
    unittest.main()

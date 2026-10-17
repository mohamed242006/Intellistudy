"""SQLiteParentStore: a persistent :class:`ai.chunking.ParentStore` for development.

The project uses SQLite during development and PostgreSQL in production (ADR-003); a
PostgreSQL implementation only has to satisfy the same four methods. Parents are context
rows, so there is no vector and no embedding anywhere in this module.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Sequence
from pathlib import Path

from ai.chunking.models import ParentChunk

_SCHEMA = """
CREATE TABLE IF NOT EXISTS parent_chunks (
    parent_key   TEXT PRIMARY KEY,
    document_uid TEXT NOT NULL,
    user_id      TEXT NOT NULL,
    course_id    TEXT NOT NULL,
    payload      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_parent_document ON parent_chunks (document_uid);
CREATE INDEX IF NOT EXISTS idx_parent_scope ON parent_chunks (user_id, course_id);
"""
_CHUNK = 500  # stays below SQLite's bound-variable limit


class SQLiteParentStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "SQLiteParentStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -------------------------------------------------------------- protocol
    def put_many(self, parents: Sequence[ParentChunk]) -> None:
        rows = [
            (
                p.store_key,
                p.document_uid,
                p.user_id,
                p.course_id,
                json.dumps(p.to_dict(), ensure_ascii=False),
            )
            for p in parents
        ]
        with self._lock, self._conn:  # one transaction: all rows or none
            self._conn.executemany(
                "INSERT OR REPLACE INTO parent_chunks "
                "(parent_key, document_uid, user_id, course_id, payload) VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def get_many(
        self, keys: Sequence[str], *, user_id: str, course_id: str
    ) -> dict[str, ParentChunk]:
        if not user_id or not course_id:
            raise ValueError("user_id and course_id are mandatory on every lookup")
        found: dict[str, ParentChunk] = {}
        ids = list(keys)
        for start in range(0, len(ids), _CHUNK):
            batch = ids[start : start + _CHUNK]
            marks = ",".join("?" * len(batch))
            with self._lock:
                cursor = self._conn.execute(
                    f"SELECT parent_key, payload FROM parent_chunks "
                    f"WHERE user_id = ? AND course_id = ? AND parent_key IN ({marks})",
                    [user_id, course_id, *batch],
                )
                rows = cursor.fetchall()
            for pid, payload in rows:
                found[pid] = ParentChunk.from_dict(json.loads(payload))
        return found

    def list_ids(self, *, document_uid: str) -> set[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT parent_key FROM parent_chunks WHERE document_uid = ?", (document_uid,)
            ).fetchall()
        return {row[0] for row in rows}

    def delete(self, keys: Sequence[str]) -> int:
        ids = list(keys)
        removed = 0
        for start in range(0, len(ids), _CHUNK):
            batch = ids[start : start + _CHUNK]
            marks = ",".join("?" * len(batch))
            with self._lock, self._conn:
                removed += self._conn.execute(
                    f"DELETE FROM parent_chunks WHERE parent_key IN ({marks})", batch
                ).rowcount
        return removed

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM parent_chunks").fetchone()[0])

"""ParentStore contract: the same tests run against the in-memory and SQLite implementations."""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai.chunking.engine import ChunkingEngine
from ai.chunking.memory_store import InMemoryParentStore
from ai.chunking.models import ChunkContext, ParentChunk
from ai.storage import SQLiteParentStore
from tests.chunk_fixtures import SMALL, H, Pg, WordCounter, build, sentences


def parents_for(uid: str = "doc-1", user: str = "u1", course: str = "c1", prefix: str = "a"):
    ctx = ChunkContext(user_id=user, course_id=course, document_uid=uid, embedding_model="fake-embed")
    blocks = [H("One"), Pg(sentences(3, prefix=prefix)), H("Two"), Pg(sentences(3, prefix=prefix + "x"))]
    return ChunkingEngine(SMALL, WordCounter()).run(build(blocks), ctx).parents


class ParentStoreContract:
    """Mixin: subclasses provide ``make_store``."""

    def make_store(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def setUp(self) -> None:
        self.store = self.make_store()

    def rich_parent(self) -> ParentChunk:
        base = parents_for()[0]
        return dataclasses.replace(
            base,
            bboxes=((1, (1.5, 2.5, 3.5, 4.5)), (2, (0.0, 0.0, 10.0, 10.0))),
            block_ranges=((1, 2), (4, 4)),
            ocr_confidence=0.75,
            section_titles=("A", "B"),
        )

    def test_roundtrip_is_lossless_including_tuple_fields(self) -> None:
        parent = self.rich_parent()
        self.store.put_many([parent])
        loaded = self.store.get_many([parent.store_key], user_id="u1", course_id="c1")[parent.store_key]

        self.assertEqual(loaded, parent)
        self.assertIsInstance(loaded.bboxes[0][1], tuple)
        self.assertIsInstance(loaded.block_ranges[0], tuple)
        self.assertIsInstance(loaded.heading_path, tuple)

    def test_scope_is_enforced(self) -> None:
        parents = parents_for()
        self.store.put_many(parents)
        ids = [p.store_key for p in parents]

        self.assertEqual(set(self.store.get_many(ids, user_id="u1", course_id="c1")), set(ids))
        self.assertEqual(self.store.get_many(ids, user_id="intruder", course_id="c1"), {})
        self.assertEqual(self.store.get_many(ids, user_id="u1", course_id="other"), {})
        with self.assertRaises(ValueError):
            self.store.get_many(ids, user_id="", course_id="c1")

    def test_unknown_ids_are_simply_missing(self) -> None:
        self.store.put_many(parents_for())

        self.assertEqual(self.store.get_many(["nope"], user_id="u1", course_id="c1"), {})
        self.assertEqual(self.store.get_many([], user_id="u1", course_id="c1"), {})

    def test_put_replaces_existing_rows(self) -> None:
        parent = parents_for()[0]
        self.store.put_many([parent])
        changed = dataclasses.replace(parent, text="rewritten text")
        self.store.put_many([changed])

        loaded = self.store.get_many([parent.store_key], user_id="u1", course_id="c1")
        self.assertEqual(loaded[parent.store_key].text, "rewritten text")
        self.assertEqual(self.store.count(), 1)

    def test_list_ids_and_delete_by_document(self) -> None:
        self.store.put_many(parents_for("doc-1"))
        self.store.put_many(parents_for("doc-2", prefix="z"))

        ids_1 = self.store.list_ids(document_uid="doc-1")
        self.assertEqual(len(ids_1), 2)
        self.assertEqual(self.store.delete(list(ids_1)), 2)
        self.assertEqual(self.store.list_ids(document_uid="doc-1"), set())
        self.assertEqual(len(self.store.list_ids(document_uid="doc-2")), 2)
        self.assertEqual(self.store.delete(["not-there"]), 0)

    def test_dict_roundtrip_through_json(self) -> None:
        parent = self.rich_parent()
        restored = ParentChunk.from_dict(json.loads(json.dumps(parent.to_dict())))

        self.assertEqual(restored, parent)


class InMemoryParentStoreTests(ParentStoreContract, unittest.TestCase):
    def make_store(self):
        return InMemoryParentStore()


class SQLiteParentStoreTests(ParentStoreContract, unittest.TestCase):
    def make_store(self):
        store = SQLiteParentStore()
        self.addCleanup(store.close)
        return store

    def test_data_survives_reopening_a_file_database(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "parents.sqlite3"
            parents = parents_for()
            with SQLiteParentStore(path) as first:
                first.put_many(parents)
            with SQLiteParentStore(path) as second:
                loaded = second.get_many([p.store_key for p in parents], user_id="u1", course_id="c1")

        self.assertEqual(set(loaded), {p.store_key for p in parents})

    def test_more_ids_than_sqlite_variable_limit(self) -> None:
        parents = parents_for()
        self.store.put_many(parents)
        ids = [p.store_key for p in parents] + [f"missing-{i}" for i in range(1500)]

        loaded = self.store.get_many(ids, user_id="u1", course_id="c1")
        self.assertEqual(set(loaded), {p.store_key for p in parents})

    def test_failed_batch_is_rolled_back(self) -> None:
        valid, other = parents_for()[:2]
        broken = dataclasses.replace(other, chunk_id="broken-1", user_id=None)  # type: ignore[arg-type]
        with self.assertRaises(sqlite3.IntegrityError):  # NOT NULL violation aborts the batch
            self.store.put_many([valid, broken])

        self.assertEqual(self.store.count(), 0)  # the valid row was rolled back too


if __name__ == "__main__":
    unittest.main()

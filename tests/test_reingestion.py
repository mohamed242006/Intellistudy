"""Re-ingestion: every kind of edit, a randomised equivalence property, and failure injection.

The central invariant: *after any sequence of edits, the incrementally maintained index is
exactly the index you would get by ingesting the final document into an empty store* -
same ids, same documents, same metadata, same vectors, same parents, and no leftovers.
"""

from __future__ import annotations

import random
import unittest

import chromadb
from chromadb.config import Settings

from ai.chunking import ChunkingEngine, IndexingService, collection_name
from ai.chunking.memory_store import InMemoryParentStore, InMemoryVectorStore
from ai.retrieval import RetrievalService
from ai.storage import SQLiteParentStore
from ai.vectorstore import ChromaVectorStore
from tests.chunk_fixtures import CTX, SMALL, FakeEmbedder, H, Pg, WordCounter, build, sentences

COLLECTION = collection_name("fake-embed")
UID = CTX.document_uid


def para(prefix: str, n: int = 3) -> str:
    return sentences(n, per=8, prefix=prefix)


class Doc:
    """A document described as an ordered list of (title, text) sections."""

    def __init__(self, sections: list[tuple[str, str]]) -> None:
        self.sections = list(sections)

    def blocks(self):
        out = []
        for title, text in self.sections:
            out += [H(title), Pg(text)]
        return out

    def chunk(self, ctx=CTX):
        return ChunkingEngine(SMALL, WordCounter()).run(build(self.blocks()), ctx)


def base_doc(n: int = 5) -> Doc:
    return Doc([(f"Section {i}", para(f"s{i}_")) for i in range(n)])


class Stack:
    """A vector store + parent store pair, plus helpers to compare complete index states."""

    def __init__(self, kind: str, test: unittest.TestCase) -> None:
        self.kind = kind
        if kind == "memory":
            self.store, self.parents = InMemoryVectorStore(), InMemoryParentStore()
        else:
            client = chromadb.EphemeralClient(settings=Settings(allow_reset=True, anonymized_telemetry=False))
            client.reset()
            test.addCleanup(client.reset)
            self.store = ChromaVectorStore(client)
            self.parents = SQLiteParentStore()
            test.addCleanup(self.parents.close)
        self.embedder = FakeEmbedder(dimension=128)
        self.service = IndexingService(self.embedder, self.store, parent_store=self.parents)

    def index(self, chunk_set, uid: str = UID):
        return self.service.index(chunk_set.children, document_uid=uid, parents=chunk_set.parents)

    def state(self, uid: str = UID) -> dict:
        """Complete, comparable snapshot of what is stored for one document."""
        ids = self.store.list_ids(COLLECTION, document_uid=uid)
        vectors = self.store.get_embeddings(COLLECTION, list(ids))
        probe = self.embedder.embed_query("w s0_0 section")
        hits = self.store.query(COLLECTION, probe, user_id="u1", course_id="c1", k=100_000,
                                filters={"document_uid": uid})
        records = {h.id: (h.document, tuple(sorted(h.metadata.items()))) for h in hits}
        return {
            "ids": ids,
            "vectors": {k: tuple(round(x, 5) for x in v) for k, v in vectors.items()},
            "records": records,
            "parents": self.parents.list_ids(document_uid=uid),
        }


class ReingestionBase:
    kind = "memory"

    def setUp(self) -> None:
        self.stack = Stack(self.kind, self)

    def assertEquivalentToFresh(self, doc: Doc, msg: str = "") -> None:
        # The in-memory stack is the reference implementation: it also proves Chroma behaves like it.
        fresh = Stack("memory", self)
        fresh.index(doc.chunk())
        self.assertEqual(self.stack.state(), fresh.state(), msg or "incremental index differs from a fresh index")


class ScenarioTests(ReingestionBase):
    def test_unchanged_file_is_a_complete_noop(self) -> None:
        doc = base_doc()
        self.stack.index(doc.chunk())
        before, calls = self.stack.state(), len(self.stack.embedder.texts_embedded)
        report = self.stack.index(doc.chunk())

        self.assertEqual((report.embedded, report.reused, report.deleted), (0, 0, 0))
        self.assertEqual(report.unchanged, len(doc.chunk().children))
        self.assertEqual(len(self.stack.embedder.texts_embedded), calls)
        self.assertEqual(self.stack.state(), before)

    def test_modified_file_one_word(self) -> None:
        doc = base_doc()
        self.stack.index(doc.chunk())
        doc.sections[2] = (doc.sections[2][0], doc.sections[2][1].replace("s2_0_0", "CHANGED"))
        report = self.stack.index(doc.chunk())

        self.assertEqual((report.embedded, report.deleted), (1, 1))
        self.assertEquivalentToFresh(doc)

    def test_partially_modified_content(self) -> None:
        doc = base_doc(6)
        self.stack.index(doc.chunk())
        for i in (1, 4):
            doc.sections[i] = (doc.sections[i][0], para(f"new{i}_"))
        report = self.stack.index(doc.chunk())

        self.assertEqual(report.embedded, 2)
        self.assertEqual(report.unchanged, 4)
        self.assertEquivalentToFresh(doc)

    def test_deleted_sections(self) -> None:
        doc = base_doc(6)
        self.stack.index(doc.chunk())
        del doc.sections[1]
        del doc.sections[3]  # originally section 4
        report = self.stack.index(doc.chunk())

        self.assertEqual(report.embedded, 0)  # nothing new to embed
        self.assertGreaterEqual(report.deleted, 2)
        self.assertEquivalentToFresh(doc)

    def test_inserted_sections_at_start_middle_end(self) -> None:
        for position in ("start", "middle", "end"):
            with self.subTest(position=position):
                self.setUp()
                doc = base_doc(4)
                self.stack.index(doc.chunk())
                new = ("Inserted", para("ins_"))
                index = {"start": 0, "middle": 2, "end": 4}[position]
                doc.sections.insert(index, new)
                report = self.stack.index(doc.chunk())

                self.assertEqual(report.embedded, 1)  # only the new section is embedded
                self.assertEquivalentToFresh(doc)

    def test_reordered_sections_reuse_every_vector(self) -> None:
        doc = base_doc(5)
        self.stack.index(doc.chunk())
        before = len(self.stack.embedder.texts_embedded)
        doc.sections.reverse()
        report = self.stack.index(doc.chunk())

        self.assertEqual(report.embedded, 0)
        self.assertEqual(len(self.stack.embedder.texts_embedded), before)
        self.assertEquivalentToFresh(doc)

    def test_duplicated_section_content(self) -> None:
        doc = base_doc(3)
        self.stack.index(doc.chunk())
        doc.sections.append(doc.sections[1])  # identical title and text again
        self.stack.index(doc.chunk())

        self.assertEquivalentToFresh(doc)
        self.assertEqual(len(self.stack.state()["ids"]), len(doc.chunk().children))

    def test_completely_replaced_document(self) -> None:
        doc = base_doc(4)
        self.stack.index(doc.chunk())
        other = Doc([(f"Other {i}", para(f"o{i}_")) for i in range(3)])
        report = self.stack.index(other.chunk())

        self.assertEqual(report.embedded, 3)
        self.assertEqual(report.deleted, 4)
        self.assertEquivalentToFresh(other)

    def test_empty_document_after_content_removes_everything(self) -> None:
        self.stack.index(base_doc().chunk())
        self.stack.index(Doc([]).chunk())

        self.assertEqual(self.stack.state(), {"ids": {}, "vectors": {}, "records": {}, "parents": set()})

    def test_index_remove_index_again(self) -> None:
        doc = base_doc()
        self.stack.index(doc.chunk())
        self.stack.service.remove_document(UID)
        self.assertEqual(self.stack.state()["ids"], {})
        self.stack.index(doc.chunk())

        self.assertEquivalentToFresh(doc)

    def test_documents_are_independent(self) -> None:
        a, b = base_doc(3), Doc([(f"B{i}", para(f"b{i}_")) for i in range(3)])
        ctx_b = CTX.__class__("u1", "c1", "doc-2", "fake-embed")
        self.stack.index(a.chunk())
        self.stack.index(b.chunk(ctx_b), uid="doc-2")
        snapshot_b = self.stack.state("doc-2")
        a.sections[0] = ("Section 0", para("edited_"))
        self.stack.index(a.chunk())

        self.assertEqual(self.stack.state("doc-2"), snapshot_b)

    def test_changed_embedding_model_uses_a_separate_collection(self) -> None:
        doc = base_doc(2)
        self.stack.index(doc.chunk())
        other_embedder = FakeEmbedder("model-b", 128)
        service = IndexingService(other_embedder, self.stack.store, parent_store=self.stack.parents)
        ctx_b = CTX.__class__("u1", "c1", UID, "model-b")
        result = doc.chunk(ctx_b)
        service.index(result.children, document_uid=UID, parents=result.parents)

        self.assertEqual(len(self.stack.store.list_ids(collection_name("model-b"), document_uid=UID)), 2)
        self.assertEqual(len(self.stack.store.list_ids(COLLECTION, document_uid=UID)), 2)

    def test_search_never_returns_a_stale_chunk_after_an_edit(self) -> None:
        doc = base_doc(3)
        self.stack.index(doc.chunk())
        doc.sections[1] = ("Section 1", para("fresh_"))
        self.stack.index(doc.chunk())
        search = RetrievalService(self.stack.embedder, self.stack.store, self.stack.parents)
        old = search.search("s1_0_0 s1_1_0 s1_2_0", user_id="u1", course_id="c1", k=20)
        new = search.search("fresh_0_0 fresh_1_0", user_id="u1", course_id="c1", k=1)

        self.assertTrue(all("s1_0_0" not in h.text for h in old.hits))
        self.assertTrue(all("s1_0_0" not in p.parent.text for p in old.parents))
        self.assertIn("fresh_0_0", new.hits[0].text)


class RandomisedEquivalenceTests(ReingestionBase):
    """Apply random edit sequences; the incremental index must equal a fresh one every step."""

    def apply_random_edit(self, rnd: random.Random, doc: Doc, counter: list[int]) -> str:
        counter[0] += 1
        tag = f"e{counter[0]}_"
        ops = ["modify", "insert", "delete", "swap", "duplicate", "retitle"]
        if len(doc.sections) < 2:
            ops = ["insert", "modify"]
        op = rnd.choice(ops)
        i = rnd.randrange(len(doc.sections)) if doc.sections else 0
        if op == "modify":
            doc.sections[i] = (doc.sections[i][0], para(tag, rnd.randint(1, 9)))
        elif op == "insert":
            doc.sections.insert(rnd.randint(0, len(doc.sections)), (f"New {counter[0]}", para(tag, rnd.randint(1, 9))))
        elif op == "delete":
            del doc.sections[i]
        elif op == "swap":
            j = rnd.randrange(len(doc.sections))
            doc.sections[i], doc.sections[j] = doc.sections[j], doc.sections[i]
        elif op == "duplicate":
            doc.sections.insert(rnd.randint(0, len(doc.sections)), doc.sections[i])
        elif op == "retitle":
            doc.sections[i] = (f"Retitled {counter[0]}", doc.sections[i][1])
        return op

    def test_incremental_index_equals_fresh_index_after_every_edit(self) -> None:
        for seed in range(6):
            with self.subTest(seed=seed):
                self.setUp()
                rnd, counter = random.Random(seed), [0]
                doc = base_doc(rnd.randint(3, 7))
                self.stack.index(doc.chunk())
                for step in range(10):
                    op = self.apply_random_edit(rnd, doc, counter)
                    self.stack.index(doc.chunk())
                    self.assertEquivalentToFresh(doc, f"seed={seed} step={step} op={op}")

    def test_repeating_the_same_index_call_never_changes_anything(self) -> None:
        doc = base_doc(6)
        for _ in range(4):
            self.stack.index(doc.chunk())
        self.assertEquivalentToFresh(doc)


class FlakyStore:
    """Delegates to a real store but fails selected operations once."""

    def __init__(self, inner, fail: set[str]) -> None:
        self._inner, self.fail = inner, set(fail)

    def __getattr__(self, name):
        target = getattr(self._inner, name)
        if name in self.fail and callable(target):
            def boom(*args, **kwargs):
                self.fail.discard(name)  # fail only once, like a transient outage
                raise ConnectionError(f"{name} failed")
            return boom
        return target


class FailureInjectionTests(ReingestionBase):
    def run_failure(self, *, vector_fail=(), parent_fail=()):
        """Index v1, then try to index v2 with failures injected, then retry cleanly."""
        v1, v2 = base_doc(4), base_doc(4)
        v2.sections[1] = ("Section 1", para("v2_"))
        v2.sections.insert(0, ("Brand new", para("brand_")))
        self.stack.index(v1.chunk())
        before = self.stack.state()

        flaky_store = FlakyStore(self.stack.store, set(vector_fail))
        flaky_parents = FlakyStore(self.stack.parents, set(parent_fail))
        service = IndexingService(self.stack.embedder, flaky_store, parent_store=flaky_parents)
        result = v2.chunk()
        with self.assertRaises(ConnectionError):
            service.index(result.children, document_uid=UID, parents=result.parents)
        after_failure = self.stack.state()

        service.index(result.children, document_uid=UID, parents=result.parents)  # retry succeeds
        return v2, before, after_failure

    def test_embedding_reuse_lookup_failure_changes_nothing(self) -> None:
        v2, before, after_failure = self.run_failure(vector_fail={"get_embeddings"})

        self.assertEqual(after_failure, before)
        self.assertEquivalentToFresh(v2)

    def test_parent_write_failure_changes_nothing_and_retry_converges(self) -> None:
        v2, before, after_failure = self.run_failure(parent_fail={"put_many"})

        self.assertEqual(after_failure, before)  # parents are written before any vector
        self.assertEquivalentToFresh(v2)

    def test_vector_upsert_failure_keeps_the_old_index_searchable_and_retry_converges(self) -> None:
        v2, before, after_failure = self.run_failure(vector_fail={"upsert"})

        self.assertEqual(after_failure["ids"], before["ids"])  # old vectors untouched
        self.assertEqual(after_failure["vectors"], before["vectors"])
        self.assertTrue(before["parents"] <= after_failure["parents"])  # old parents still resolvable
        self.assertEquivalentToFresh(v2)

    def test_vector_delete_failure_leaves_extra_vectors_that_a_retry_removes(self) -> None:
        v2, before, after_failure = self.run_failure(vector_fail={"delete"})

        self.assertTrue(set(after_failure["ids"]) > set(before["ids"]) or set(after_failure["ids"]) != set(before["ids"]))
        self.assertGreater(len(after_failure["ids"]), len(v2.chunk().children))  # stale leftovers exist...
        self.assertEquivalentToFresh(v2)                                          # ...and the retry cleans them

    def test_parent_delete_failure_leaves_stale_parents_that_a_retry_removes(self) -> None:
        v2, _, after_failure = self.run_failure(parent_fail={"delete"})

        self.assertGreater(len(after_failure["parents"]), len(v2.chunk().parents))
        self.assertEquivalentToFresh(v2)

    def test_old_chunks_remain_retrievable_during_a_failed_update(self) -> None:
        v1 = base_doc(3)
        self.stack.index(v1.chunk())
        v2 = base_doc(3)
        v2.sections[0] = ("Section 0", para("zz_"))
        flaky = IndexingService(self.stack.embedder, FlakyStore(self.stack.store, {"upsert"}),
                                parent_store=self.stack.parents)
        result = v2.chunk()
        with self.assertRaises(ConnectionError):
            flaky.index(result.children, document_uid=UID, parents=result.parents)

        search = RetrievalService(self.stack.embedder, self.stack.store, self.stack.parents)
        hit = search.search("s0_0_0 s0_1_0", user_id="u1", course_id="c1", k=1)
        self.assertIn("s0_0_0", hit.hits[0].text)
        self.assertIsNotNone(hit.parent_for(hit.hits[0]))  # its parent is still there too


class MemoryReingestion(ReingestionBase):
    pass


for _name, _base in (("Scenario", ScenarioTests), ("Randomised", RandomisedEquivalenceTests),
                     ("Failure", FailureInjectionTests)):
    globals()[f"Chroma{_name}Tests"] = type(f"Chroma{_name}Tests", (_base, unittest.TestCase), {"kind": "chroma"})
    _base.__bases__
    globals()[f"Memory{_name}Tests"] = type(f"Memory{_name}Tests", (_base, unittest.TestCase), {"kind": "memory"})

# the abstract bases must not be collected on their own
del ScenarioTests, RandomisedEquivalenceTests, FailureInjectionTests, MemoryReingestion

if __name__ == "__main__":
    unittest.main()

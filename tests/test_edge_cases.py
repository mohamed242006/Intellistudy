"""Cross-cutting edge cases: hostile text, odd identifiers, degenerate counters and configs,
thread safety and model helpers."""

from __future__ import annotations

import dataclasses
import json
import threading
import unittest

import chromadb
from chromadb.config import Settings

from ai.chunking import (
    ChildChunk,
    ChunkConfig,
    ChunkContext,
    ChunkingEngine,
    IndexingService,
    InMemoryVectorStore,
)
from ai.chunking.memory_store import InMemoryParentStore
from ai.ingestion.cleaners import clean_text
from ai.ingestion.models import Block, BlockType, Document, PageContent
from ai.ingestion.structure import assign_heading_paths, finalize_document, render_blocks
from ai.retrieval import RetrievalService
from ai.storage import SQLiteParentStore
from ai.vectorstore import ChromaVectorStore
from tests.chunk_fixtures import CTX, SMALL, FakeEmbedder, H, Pg, WordCounter, build, sentences
from tests.random_docs import random_document


def run_with_timeout(fn, seconds: float = 20.0):
    """Run ``fn`` in a thread; fail the test (instead of hanging) if it does not finish."""
    box: dict = {}

    def target() -> None:
        try:
            box["result"] = fn()
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise AssertionError(f"did not finish within {seconds}s (possible infinite loop)")
    if "error" in box:
        raise box["error"]
    return box["result"]


class HostileTextTests(unittest.TestCase):
    """REG-13 and friends: text that real extractors emit must never crash the stack."""

    NASTY = [
        "lone surrogate " + chr(0xD800) + " and " + chr(0xDFFF) + " here",
        "nul \x00 and bell \x07 and escape \x1b characters inside",
        "zero\u200bwidth\u2060joiners\ufeffeverywhere in this sentence now",
        "combining é and NFD café text with accents",
        "emoji family \U0001f468\u200d\U0001f469\u200d\U0001f467 and flags \U0001f1ea\U0001f1ec here",
        "rtl \u202e override \u202c and isolates \u2067x\u2069 inside text",
        "tabs\tand\r\nwindows\rline\nendings mixed",
        "\ufffd\ufffd\ufffd replacement characters everywhere \ufffd",
        "x" * 5000,
    ]

    def test_clean_text_output_is_always_encodable_and_idempotent(self) -> None:
        for text in self.NASTY:
            with self.subTest(text=ascii(text[:30])):
                cleaned = clean_text(text)
                cleaned.encode("utf-8")  # must not raise
                self.assertEqual(clean_text(cleaned), cleaned)
                self.assertNotIn("\x00", cleaned)
                self.assertFalse(any(0xD800 <= ord(ch) <= 0xDFFF for ch in cleaned))

    def test_chunking_and_indexing_survive_raw_hostile_text(self) -> None:
        """Even text that skipped clean_text (e.g. a custom reader) must not crash the stack."""
        for text in self.NASTY:
            with self.subTest(text=ascii(text[:30])):
                doc = build([H("Hostile"), Pg((text + ". ") * 5)])
                result = ChunkingEngine(SMALL, WordCounter(), strict=True).run(doc, CTX)
                for child in result.children:
                    self.assertTrue(child.content_hash)
                    child.text.encode("utf-8", "surrogatepass")
                self.assertIsInstance(result.children, list)

    def test_hostile_text_round_trips_through_the_sql_parent_store(self) -> None:
        text = "quote ' double \" semicolon ; -- comment /* x */ percent % underscore _ backslash \\"
        result = ChunkingEngine(SMALL, WordCounter()).run(build([H(text), Pg(sentences(3))]), CTX)
        with SQLiteParentStore() as store:
            store.put_many(result.parents)
            loaded = store.get_many([p.store_key for p in result.parents], user_id="u1", course_id="c1")

        self.assertEqual(list(loaded.values()), result.parents)


class OddIdentifierTests(unittest.TestCase):
    IDS = ["a:b", "with space", "ünï-çödé-文档", "q'uo\"te", "x" * 300, "percent%20", "slash/backslash\\", "dot.dot"]

    def stacks(self):
        yield InMemoryVectorStore(), InMemoryParentStore()
        client = chromadb.EphemeralClient(settings=Settings(allow_reset=True, anonymized_telemetry=False))
        client.reset()
        self.addCleanup(client.reset)
        parents = SQLiteParentStore()
        self.addCleanup(parents.close)
        yield ChromaVectorStore(client), parents

    def test_unusual_user_course_and_document_ids_work_end_to_end(self) -> None:
        for store, parents in self.stacks():
            embedder = FakeEmbedder(dimension=128)
            indexer = IndexingService(embedder, store, parent_store=parents)
            engine = ChunkingEngine(SMALL, WordCounter())
            retrieval = RetrievalService(embedder, store, parents)
            for ident in self.IDS:
                with self.subTest(store=type(store).__name__, ident=ident[:20]):
                    ctx = ChunkContext(user_id=ident, course_id=ident, document_uid=ident, embedding_model="fake-embed")
                    result = engine.run(build([H("Topic"), Pg(sentences(3, prefix="odd"))]), ctx)
                    indexer.index(result.children, document_uid=ident, parents=result.parents)
                    found = retrieval.search("odd0_0 odd1_0", user_id=ident, course_id=ident, k=3)
                    self.assertTrue(found.hits)
                    self.assertEqual({h.document_uid for h in found.hits}, {ident})
                    self.assertIsNotNone(found.parent_for(found.hits[0]))

    def test_one_tenants_odd_id_never_matches_another(self) -> None:
        store, parents = InMemoryVectorStore(), InMemoryParentStore()
        embedder = FakeEmbedder(dimension=128)
        indexer = IndexingService(embedder, store, parent_store=parents)
        engine = ChunkingEngine(SMALL, WordCounter())
        for ident in ("a:b", "a"):
            ctx = ChunkContext(ident, "c", ident, "fake-embed")
            result = engine.run(build([H("T"), Pg(sentences(3))]), ctx)
            indexer.index(result.children, document_uid=ident, parents=result.parents)
        retrieval = RetrievalService(embedder, store, parents)

        self.assertEqual({h.user_id for h in retrieval.search("s0_0", user_id="a", course_id="c", k=9).hits}, {"a"})
        self.assertEqual({h.user_id for h in retrieval.search("s0_0", user_id="a:b", course_id="c", k=9).hits}, {"a:b"})


class DegenerateCounterTests(unittest.TestCase):
    """A broken TokenCounter must degrade gracefully, never hang or crash."""

    def chunk(self, counter, text=None):
        doc = build([H("A"), Pg(text or sentences(40, per=10))])
        return run_with_timeout(lambda: ChunkingEngine(SMALL, counter).run(doc, CTX))

    def test_counter_that_always_returns_zero(self) -> None:
        class Zero:
            name = "zero"

            def count(self, text: str) -> int:
                return 0

        result = self.chunk(Zero())
        self.assertTrue(result.children)  # everything fits "for free": one big chunk, no hang

    def test_counter_that_counts_every_character_as_a_token(self) -> None:
        class PerChar:
            name = "per-char"

            def count(self, text: str) -> int:
                return len(text)

        result = self.chunk(PerChar(), "short text. " * 30)
        self.assertTrue(result.children)

    def test_counter_that_returns_huge_numbers(self) -> None:
        class Huge:
            name = "huge"

            def count(self, text: str) -> int:
                return 10**6 if text.strip() else 0

        result = self.chunk(Huge(), "a few words in a short paragraph. Another sentence follows here.")
        self.assertTrue(result.children)  # oversize is flagged, not looped on
        self.assertTrue(all(c.oversize for c in result.children))


class ConfigExtremesTests(unittest.TestCase):
    def test_tiny_configuration_still_satisfies_every_invariant(self) -> None:
        tiny = ChunkConfig(target_tokens=6, max_tokens=10, min_tokens=2, overlap_tokens=2,
                           slide_min_body_tokens=1, table_max_tokens=6, context_max_tokens=3,
                           prefix_max_tokens=3, parent_max_tokens=20)
        for unit in ("page", "slide", "document"):
            for seed in range(6):
                with self.subTest(unit=unit, seed=seed):
                    doc = random_document(seed, unit=unit, sections=5, max_paragraph=40).document
                    result = run_with_timeout(lambda: ChunkingEngine(tiny, WordCounter()).run(doc, CTX))
                    self.assertEqual([p for p in result.report.problems if "max_tokens" not in p], [])
                    self.assertLessEqual(max((c.token_count for c in result.children), default=0), 10 + 3)

    def test_huge_configuration_yields_few_large_chunks(self) -> None:
        big = ChunkConfig(target_tokens=50_000, max_tokens=60_000, min_tokens=100, overlap_tokens=100,
                          table_max_tokens=50_000, parent_max_tokens=100_000, prefix_max_tokens=100)
        doc = random_document(5, unit="document", sections=6).document
        strict = ChunkingEngine(big, WordCounter(), strict=True).run(doc, CTX)
        default = ChunkingEngine(ChunkConfig(), WordCounter()).run(doc, CTX)

        # section boundaries and isolated atoms (tables, charts, notes) set a floor on the count
        self.assertLessEqual(len(strict.children), len(default.children))
        self.assertGreaterEqual(max(c.token_count for c in strict.children),
                                max(c.token_count for c in default.children))


class ThreadSafetyTests(unittest.TestCase):
    def test_one_engine_shared_by_many_threads_gives_identical_results(self) -> None:
        engine = ChunkingEngine(SMALL, WordCounter())
        docs = [random_document(s, unit="page").document for s in range(4)]
        expected = [engine.run(d, CTX) for d in docs]
        results: dict[int, object] = {}

        def work(i: int) -> None:
            results[i] = engine.run(docs[i % 4], CTX)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i in range(16):
            self.assertEqual(results[i], expected[i % 4])


class ModelHelperTests(unittest.TestCase):
    def test_block_and_chunk_serialisation(self) -> None:
        block = Block(BlockType.TABLE, "x", 3, order=5, level=None, heading_path=("A", "B"),
                      ref_index=2, bbox=(1.0, 2.0, 3.0, 4.0), confidence=0.5)
        data = block.to_dict()

        self.assertEqual(json.loads(json.dumps(data))["heading_path"], ["A", "B"])
        self.assertEqual(data["bbox"], [1.0, 2.0, 3.0, 4.0])
        self.assertFalse(block.is_heading)

    def test_chunk_dataclasses_are_immutable(self) -> None:
        child = ChunkingEngine(SMALL, WordCounter()).chunk(build([H("A"), Pg(sentences(2))]), CTX)[0]

        with self.assertRaises(dataclasses.FrozenInstanceError):
            child.text = "changed"  # type: ignore[misc]
        self.assertIsInstance(child, ChildChunk)
        self.assertEqual(dataclasses.replace(child, text="x").text, "x")

    def test_document_helpers_on_degenerate_documents(self) -> None:
        empty = Document(source_path="x")
        self.assertEqual((empty.full_text, empty.blocks, empty.unit, empty.get_page(1)), ("", [], "page", None))
        page = PageContent(page_number=2, final_text="body")
        doc = Document(source_path="x", pages=[page])
        self.assertEqual(doc.full_text, "[Page 2]\nbody")
        self.assertIs(doc.get_page(2), page)

    def test_heading_paths_handle_odd_level_sequences(self) -> None:
        blocks = [Block(BlockType.HEADING, t, 1, level=lvl) for t, lvl in
                  [("d", 4), ("c", 2), ("e", 2), ("f", 1), ("g", 6), ("h", 6)]]
        assign_heading_paths(blocks)

        self.assertEqual([b.heading_path for b in blocks],
                         [("d",), ("c",), ("e",), ("f",), ("f", "g"), ("f", "h")])

    def test_render_blocks_skips_empty_text_and_keeps_lists_tight(self) -> None:
        blocks = [Block(BlockType.PARAGRAPH, "  ", 1), Block(BlockType.LIST_ITEM, "a", 1, level=0, list_marker="-"),
                  Block(BlockType.LIST_ITEM, "b", 1, level=1, list_marker="-"), Block(BlockType.PARAGRAPH, "end", 1)]

        self.assertEqual(render_blocks(blocks), "- a\n  - b\n\nend")

    def test_finalize_document_is_idempotent(self) -> None:
        doc = build([H("A"), Pg(sentences(2)), H("B", 2), Pg(sentences(2, prefix="b"))])
        first = [(b.order, b.heading_path) for b in doc.blocks]
        finalize_document(doc)

        self.assertEqual([(b.order, b.heading_path) for b in doc.blocks], first)


if __name__ == "__main__":
    unittest.main()

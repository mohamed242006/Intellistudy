"""RetrievalService: semantic search, scoping, filters, and parent-child expansion.

Every scenario runs on two stacks: in-memory stores, and ChromaDB + SQLite parent store.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import chromadb
from chromadb.config import Settings

from ai.chunking.engine import ChunkingEngine
from ai.chunking.indexing import IndexingService
from ai.chunking.memory_store import InMemoryParentStore, InMemoryVectorStore
from ai.chunking.models import ChunkContext
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.ingestion.models import Block
from ai.retrieval import RetrievalService, RetrievedChunk
from ai.storage import SQLiteParentStore
from ai.vectorstore import ChromaVectorStore
from tests import pdf_fixtures as pf
from tests.chunk_fixtures import OCR, SMALL, FakeEmbedder, H, Pg, WordCounter, build, sentences


def ctx(uid: str, user: str = "u1", course: str = "c1") -> ChunkContext:
    return ChunkContext(user_id=user, course_id=course, document_uid=uid, embedding_model="fake-embed")


def corpus() -> list[Block]:
    return [
        H("Caching"),
        Pg("lru cache eviction removes the least recently used entry when the cache is full today."),
        H("Networking"),
        Pg("tcp handshake uses syn and ack packets between the client and the server before data."),
        H("Deadlocks"),
        Pg(sentences(6, per=9, prefix="dl")),  # 54 words -> two child chunks, one parent
    ]


class RetrievalTestCase(unittest.TestCase):
    """Backend-agnostic scenarios; subclasses choose the stores."""

    def new_stores(self):
        return InMemoryVectorStore(), InMemoryParentStore()

    def setUp(self) -> None:
        self.embedder = FakeEmbedder(dimension=512)  # wide enough that hash collisions are negligible
        self.store, self.parent_store = self.new_stores()
        self.indexer = IndexingService(self.embedder, self.store, parent_store=self.parent_store)
        self.engine = ChunkingEngine(SMALL, WordCounter())
        self.service = RetrievalService(self.embedder, self.store, self.parent_store)
        self.sets = {}
        self.index(corpus(), ctx("doc-1"))                                   # u1 / c1
        self.index([H("Databases"), Pg("sql join combines rows from two tables using a key now.")],
                   ctx("doc-3"))                                             # u1 / c1, second document
        self.index(corpus(), ctx("doc-2", user="u2", course="c2"))           # other user: identical file

    def index(self, blocks, context: ChunkContext):
        chunk_set = self.engine.run(build(blocks), context)
        self.indexer.index(chunk_set.children, document_uid=context.document_uid, parents=chunk_set.parents)
        self.sets[context.document_uid] = chunk_set
        return chunk_set

    def search(self, query: str, **kwargs):
        kwargs.setdefault("user_id", "u1")
        kwargs.setdefault("course_id", "c1")
        return self.service.search(query, **kwargs)


class SemanticSearchTests(RetrievalTestCase):
    def test_best_child_is_first_and_carries_citation_fields(self) -> None:
        result = self.search("least recently used cache eviction")
        top = result.hits[0]

        self.assertIsInstance(top, RetrievedChunk)
        self.assertEqual(top.heading_path, ("Caching",))
        self.assertEqual(top.citation_label, "p. 1 > Caching")
        self.assertEqual((top.page_number, top.slide_number), (1, None))
        self.assertEqual(top.block_types, ("paragraph",))
        self.assertIsNone(top.ocr_confidence)
        self.assertFalse(top.low_confidence)
        self.assertEqual((top.user_id, top.course_id, top.document_uid), ("u1", "c1", "doc-1"))
        self.assertTrue(top.text.startswith("lru cache eviction"))
        self.assertEqual(top.kind, "text")
        scores = [h.score for h in result.hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_top_k_limits_the_number_of_hits(self) -> None:
        self.assertEqual(len(self.search("cache tcp sql", k=1).hits), 1)
        self.assertLessEqual(len(self.search("cache tcp sql", k=3).hits), 3)
        self.assertEqual(len(self.search("cache tcp sql", k=50).hits),
                         sum(len(self.sets[d].children) for d in ("doc-1", "doc-3")))

    def test_different_queries_find_different_sections(self) -> None:
        self.assertEqual(self.search("tcp syn ack handshake").hits[0].heading_path, ("Networking",))
        self.assertEqual(self.search("sql join tables").hits[0].heading_path, ("Databases",))

    def test_query_uses_the_query_embedding_path(self) -> None:
        calls = []
        original = self.embedder.embed_query
        self.embedder.embed_query = lambda text: calls.append(text) or original(text)  # type: ignore[method-assign]
        self.search("tcp handshake")

        self.assertEqual(calls, ["tcp handshake"])

    def test_invalid_requests_are_rejected(self) -> None:
        for kwargs in ({"query": "  "}, {"query": "x", "k": 0}, {"query": "x", "user_id": ""},
                       {"query": "x", "course_id": ""}):
            with self.subTest(kwargs=kwargs):
                query = kwargs.pop("query")
                with self.assertRaises(ValueError):
                    self.search(query, **kwargs)

    def test_empty_index_returns_an_empty_result(self) -> None:
        store, parents = self.new_stores()
        empty = RetrievalService(self.embedder, store, parents)
        result = empty.search("anything", user_id="u1", course_id="c1")

        self.assertTrue(result.is_empty)
        self.assertEqual((result.hits, result.parents), ([], []))


class ScopingTests(RetrievalTestCase):
    def test_users_only_see_their_own_content(self) -> None:
        mine = self.search("lru cache eviction", k=20)
        theirs = self.search("lru cache eviction", k=20, user_id="u2", course_id="c2")

        self.assertTrue(mine.hits and theirs.hits)
        self.assertEqual({h.document_uid for h in mine.hits}, {"doc-1", "doc-3"})
        self.assertEqual({h.document_uid for h in theirs.hits}, {"doc-2"})
        self.assertTrue(all(h.user_id == "u2" for h in theirs.hits))

    def test_unknown_user_or_course_gets_nothing(self) -> None:
        self.assertTrue(self.search("cache", user_id="intruder").is_empty)
        self.assertTrue(self.search("cache", course_id="c2").is_empty)   # right user, wrong course
        self.assertTrue(self.search("cache", user_id="u2").is_empty)     # right course id, wrong owner

    def test_identical_files_of_two_users_keep_separate_parents(self) -> None:
        mine = self.search("dl0_0 dl1_0", k=5)
        theirs = self.search("dl0_0 dl1_0", k=5, user_id="u2", course_id="c2")

        self.assertEqual(mine.hits[0].chunk_id, theirs.hits[0].chunk_id)  # same file, same chunk id
        self.assertEqual(mine.parents[0].parent.user_id, "u1")
        self.assertEqual(theirs.parents[0].parent.user_id, "u2")
        self.assertEqual(mine.parents[0].parent.document_uid, "doc-1")
        self.assertEqual(theirs.parents[0].parent.document_uid, "doc-2")

    def test_document_filter(self) -> None:
        only_3 = self.search("cache tcp sql", k=10, document_uids=["doc-3"])
        both = self.search("cache tcp sql", k=10, document_uids=["doc-1", "doc-3"])

        self.assertEqual({h.document_uid for h in only_3.hits}, {"doc-3"})
        self.assertEqual({h.document_uid for h in both.hits}, {"doc-1", "doc-3"})
        self.assertTrue(self.search("cache", document_uids=[]).is_empty)

    def test_metadata_filters_and_reserved_keys(self) -> None:
        networking = self.search("cache tcp sql", k=10, filters={"heading_top": "Networking"})

        self.assertEqual({h.heading_path for h in networking.hits}, {("Networking",)})
        with self.assertRaises(ValueError):
            self.search("cache", filters={"user_id": "u2"})


class QualityControlTests(RetrievalTestCase):
    def test_min_score_turns_irrelevant_queries_into_empty_results(self) -> None:
        self.assertTrue(self.search("zzzz qqqq wwww", min_score=0.5).is_empty)
        self.assertFalse(self.search("lru cache eviction", min_score=0.2).is_empty)

    def test_low_confidence_chunks_can_be_excluded_and_are_flagged(self) -> None:
        blocks = [H("Scan"), OCR("blurry diagram showing kernel scheduler queues", 0.45)]
        self.index(blocks, ctx("doc-4"))

        included = self.search("blurry diagram kernel scheduler queues", k=1)
        excluded = self.search("blurry diagram kernel scheduler queues", k=20, include_low_confidence=False)

        self.assertTrue(included.hits[0].low_confidence)
        self.assertAlmostEqual(included.hits[0].ocr_confidence, 0.45, places=2)
        self.assertEqual(included.hits[0].block_types, ("image_ocr",))
        self.assertTrue(all(not h.low_confidence for h in excluded.hits))
        self.assertNotIn("doc-4", {h.document_uid for h in excluded.hits})


class ParentExpansionTests(RetrievalTestCase):
    def test_children_come_first_and_parents_expand_them(self) -> None:
        result = self.search("least recently used cache eviction")
        hit = result.hits[0]
        context = result.parent_for(hit)

        self.assertIsNotNone(context)
        self.assertEqual(context.parent.chunk_id, hit.parent_chunk_id)
        self.assertIn(hit.chunk_id, context.hit_chunk_ids)
        self.assertIn(hit.text, context.parent.text)           # parent contains the child
        self.assertEqual(context.parent.heading_path, hit.heading_path)
        self.assertEqual(context.parent.citation_label, hit.citation_label)
        self.assertEqual(context.best_score, hit.score)
        self.assertEqual(context.parent.kind, "section")

    def test_sibling_hits_share_a_single_parent(self) -> None:
        # words from the first and the second child of the "Deadlocks" section
        result = self.search("dl0_0 dl1_0 dl2_0 dl4_0 dl5_0", k=5, document_uids=["doc-1"])
        deadlock_hits = [h for h in result.hits if h.heading_path == ("Deadlocks",)]

        self.assertGreaterEqual(len(deadlock_hits), 2)
        self.assertEqual(len({h.parent_chunk_id for h in deadlock_hits}), 1)
        contexts = [p for p in result.parents if p.parent.heading_path == ("Deadlocks",)]
        self.assertEqual(len(contexts), 1)                       # parent returned once
        self.assertEqual(set(contexts[0].hit_chunk_ids), {h.chunk_id for h in deadlock_hits})

    def test_parents_are_ordered_by_their_best_child(self) -> None:
        result = self.search("tcp handshake syn ack lru cache", k=5, document_uids=["doc-1"])
        order = [h.parent_chunk_id for h in result.hits]
        expected = list(dict.fromkeys(order))

        self.assertEqual([p.parent.chunk_id for p in result.parents], expected)

    def test_expansion_can_be_disabled(self) -> None:
        result = self.search("lru cache", expand_parents=False)

        self.assertTrue(result.hits)
        self.assertEqual(result.parents, [])

    def test_missing_parent_store_is_reported_not_fatal(self) -> None:
        service = RetrievalService(self.embedder, self.store, parent_store=None)
        result = service.search("lru cache", user_id="u1", course_id="c1")

        self.assertTrue(result.hits)
        self.assertEqual(result.parents, [])
        self.assertTrue(any("no parent store" in w for w in result.warnings))

    def test_a_missing_parent_row_only_produces_a_warning(self) -> None:
        hit = self.search("tcp handshake").hits[0]
        parent = self.sets["doc-1"].parent_of(next(c for c in self.sets["doc-1"].children
                                                   if c.chunk_id == hit.chunk_id))
        self.parent_store.delete([parent.store_key])
        result = self.search("tcp handshake")

        self.assertEqual(result.hits[0].chunk_id, hit.chunk_id)
        self.assertIsNone(result.parent_for(result.hits[0]))
        self.assertTrue(any("not found" in w for w in result.warnings))

    def test_parent_token_budget_keeps_the_best_and_drops_the_rest(self) -> None:
        result = self.search("tcp handshake syn ack lru cache sql", k=5, parent_token_budget=1)

        self.assertEqual(len(result.parents), 1)
        self.assertEqual(result.parents[0].parent.chunk_id, result.hits[0].parent_chunk_id)
        self.assertTrue(any("budget" in w for w in result.warnings))

    def test_parents_are_never_embedded(self) -> None:
        parent_texts = {p.text for s in self.sets.values() for p in s.parents}

        self.assertTrue(parent_texts)
        self.assertFalse(parent_texts & set(self.embedder.texts_embedded))
        self.assertEqual(self.store.count("chunks__fake-embed__c1"),
                         sum(len(s.children) for s in self.sets.values()))


class ReingestionRetrievalTests(RetrievalTestCase):
    def test_edited_content_replaces_old_content_in_search_and_context(self) -> None:
        edited = [b if b.text != corpus()[3].text else Pg("udp is connectionless and sends datagrams without handshake.")
                  for b in corpus()]
        self.index(edited, ctx("doc-1"))

        result = self.search("udp datagrams connectionless", k=10, document_uids=["doc-1"])
        self.assertEqual(result.hits[0].heading_path, ("Networking",))
        self.assertIn("udp", result.hits[0].text)
        self.assertIn("udp", result.parents[0].parent.text)
        stale = self.search("tcp handshake syn ack", k=10, document_uids=["doc-1"])
        self.assertTrue(all("syn and ack" not in h.text for h in stale.hits))
        self.assertTrue(all("syn and ack" not in p.parent.text for p in stale.parents))

    def test_removed_document_disappears_from_retrieval(self) -> None:
        self.indexer.remove_document("doc-3")

        self.assertTrue(self.search("sql join", document_uids=["doc-3"]).is_empty)
        self.assertEqual(self.parent_store.list_ids(document_uid="doc-3"), set())


class RealIngestionTests(RetrievalTestCase):
    def test_pdf_through_the_real_pipeline(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            pages = [[("Memory Management", 24.0), ("Paging", 16.0),
                      ("Paging splits virtual memory into fixed size pages mapped to frames.", 11.0),
                      ("The page table translates virtual page numbers to physical frames.", 11.0),
                      ("A translation lookaside buffer caches recent page table entries.", 11.0)]]
            document = IngestionPipeline().ingest(pf.make_pdf(Path(tmp) / "os.pdf", pages))
        context = ctx("doc-pdf")
        chunk_set = self.engine.run(document, context)
        self.indexer.index(chunk_set.children, document_uid="doc-pdf", parents=chunk_set.parents)

        result = self.search("how does the page table translate virtual pages to frames",
                             document_uids=["doc-pdf"])
        self.assertEqual(result.hits[0].heading_path, ("Memory Management", "Paging"))
        self.assertEqual(result.hits[0].citation_label, "p. 1 > Memory Management > Paging")
        self.assertIn("page table", result.parents[0].parent.text)


# ---- the same scenarios on ChromaDB + SQLite -----------------------------------------------
class ChromaStack:
    def new_stores(self):
        client = chromadb.EphemeralClient(settings=Settings(allow_reset=True, anonymized_telemetry=False))
        client.reset()
        self.addCleanup(client.reset)
        parents = SQLiteParentStore()
        self.addCleanup(parents.close)
        return ChromaVectorStore(client), parents


class ChromaSemanticSearch(ChromaStack, SemanticSearchTests):
    pass


class ChromaScoping(ChromaStack, ScopingTests):
    pass


class ChromaQualityControl(ChromaStack, QualityControlTests):
    pass


class ChromaParentExpansion(ChromaStack, ParentExpansionTests):
    pass


class ChromaReingestionRetrieval(ChromaStack, ReingestionRetrievalTests):
    pass


class ChromaRealIngestion(ChromaStack, RealIngestionTests):
    pass


# ---- end to end with the REAL model (opt-in) ---------------------------------------------------
@unittest.skipUnless(os.environ.get("INTELLISTUDY_MODEL_TESTS") == "1", "set INTELLISTUDY_MODEL_TESTS=1")
class RealModelEndToEnd(unittest.TestCase):
    def test_bge_chroma_sqlite_pipeline(self) -> None:
        from ai.chunking import EMBEDDING_MODEL, default_token_counter
        from ai.embedding import BgeEmbedder

        client = chromadb.EphemeralClient(settings=Settings(allow_reset=True, anonymized_telemetry=False))
        client.reset()
        self.addCleanup(client.reset)
        parents = SQLiteParentStore()
        self.addCleanup(parents.close)
        store, embedder = ChromaVectorStore(client), BgeEmbedder()
        blocks = [
            H("Caching"), Pg("LRU eviction removes the least recently used entry when the cache is full. "
                             "It is implemented with a hash map and a doubly linked list."),
            H("Networking"), Pg("The TCP three-way handshake establishes a connection using SYN, SYN-ACK and ACK."),
            H("Processes"), Pg("A deadlock happens when processes wait for each other in a cycle forever."),
        ]
        context = ChunkContext("u1", "c1", "doc-real", EMBEDDING_MODEL)
        engine = ChunkingEngine(tokenizer=default_token_counter(), strict=True)
        chunk_set = engine.run(build(blocks), context)
        IndexingService(embedder, store, parent_store=parents).index(
            chunk_set.children, document_uid="doc-real", parents=chunk_set.parents)

        service = RetrievalService(embedder, store, parents)
        for question, heading in (("Which entry does an LRU cache throw out?", "Caching"),
                                  ("How is a TCP connection established?", "Networking"),
                                  ("Why can processes get stuck waiting on each other?", "Processes")):
            with self.subTest(question=question):
                result = service.search(question, user_id="u1", course_id="c1", k=3)
                self.assertEqual(result.hits[0].heading_path, (heading,))
                self.assertEqual(result.parents[0].parent.heading_path, (heading,))
        unrelated = service.search("What is the capital of France?", user_id="u1", course_id="c1", k=3)
        self.assertLess(unrelated.hits[0].score, service.search(
            "Which entry does an LRU cache throw out?", user_id="u1", course_id="c1", k=1).hits[0].score)


if __name__ == "__main__":
    unittest.main()

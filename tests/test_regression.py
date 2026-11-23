"""Regression tests: one per defect found during the validation phase.

Each test names the defect (REG-nn) and would fail on the code as it was before the fix.
REG-04 (concurrent ingestion) lives in test_ingestion.ConcurrencyTests; REG-01..03 in
test_chunking.HardLimitRegressionTests; REG-06 in test_chroma.FilterTests; REG-05 in
test_embeddings.BadModelOutputTests; REG-10 in test_chroma.CollectionNamingTests.
"""

from __future__ import annotations

import unittest

import chromadb
from chromadb.config import Settings

from ai.chunking import ChunkingEngine, IndexingService, InMemoryVectorStore, collection_name
from ai.chunking.memory_store import InMemoryParentStore
from ai.chunking.text import TextSplitter
from ai.chunking.tokens import ApproxTokenCounter
from ai.ingestion.cleaners import clean_text
from ai.ingestion.models import BlockType
from ai.retrieval import RetrievalService
from ai.storage import SQLiteParentStore
from ai.vectorstore import ChromaVectorStore
from tests.chunk_fixtures import CTX, SMALL, FakeEmbedder, H, Pg, WordCounter, build, sentences

COLLECTION = collection_name("fake-embed")


def stacks(test: unittest.TestCase):
    yield InMemoryVectorStore(), InMemoryParentStore()
    client = chromadb.EphemeralClient(settings=Settings(allow_reset=True, anonymized_telemetry=False))
    client.reset()
    parents = SQLiteParentStore()
    test.addCleanup(client.reset)
    test.addCleanup(parents.close)
    yield ChromaVectorStore(client), parents


class Reg07InvisibleTextTests(unittest.TestCase):
    def test_text_made_only_of_invisible_characters_is_not_indexed(self) -> None:
        for text in ("\u00a0\u200b", "\u200b\u2060\ufeff", "\u200c\u200d", "\x00\x01", "\u2028\u2029"):
            with self.subTest(text=ascii(text)):
                chunks = ChunkingEngine(SMALL, WordCounter()).chunk(build([H("A"), Pg(text)]), CTX)
                self.assertEqual(chunks, [])

    def test_invisible_characters_inside_real_text_are_removed(self) -> None:
        self.assertEqual(clean_text("cach\u200be mi\u2060ss"), "cache miss")
        self.assertEqual(clean_text("keep\u200djoiner\u200cand non-joiner"), "keep\u200djoiner\u200cand non-joiner")


class Reg08ParentCollisionTests(unittest.TestCase):
    """Two users uploading the same file share chunk and parent ids; parents must not clash."""

    def test_second_users_upload_does_not_overwrite_the_first_users_parents(self) -> None:
        for store, parents in stacks(self):
            embedder = FakeEmbedder(dimension=128)
            indexer = IndexingService(embedder, store, parent_store=parents)
            blocks = [H("Shared"), Pg(sentences(6, per=9, prefix="same"))]
            for user, uid in (("alice", "doc-a"), ("bob", "doc-b")):
                ctx = CTX.__class__(user, "c1", uid, "fake-embed")
                result = ChunkingEngine(SMALL, WordCounter()).run(build(blocks), ctx)
                indexer.index(result.children, document_uid=uid, parents=result.parents)
            search = RetrievalService(embedder, store, parents)

            with self.subTest(store=type(store).__name__):
                for user in ("alice", "bob"):
                    result = search.search("same0_0 same1_0", user_id=user, course_id="c1", k=3)
                    self.assertTrue(result.parents)
                    self.assertEqual({p.parent.user_id for p in result.parents}, {user})
                    self.assertEqual(result.warnings, [])

    def test_removing_one_users_document_keeps_the_other(self) -> None:
        for store, parents in stacks(self):
            embedder = FakeEmbedder(dimension=128)
            indexer = IndexingService(embedder, store, parent_store=parents)
            blocks = [H("Shared"), Pg(sentences(6, per=9, prefix="same"))]
            for user, uid in (("alice", "doc-a"), ("bob", "doc-b")):
                ctx = CTX.__class__(user, "c1", uid, "fake-embed")
                result = ChunkingEngine(SMALL, WordCounter()).run(build(blocks), ctx)
                indexer.index(result.children, document_uid=uid, parents=result.parents)
            indexer.remove_document("doc-a")

            with self.subTest(store=type(store).__name__):
                bob = RetrievalService(embedder, store, parents).search("same0_0", user_id="bob", course_id="c1")
                self.assertTrue(bob.hits and bob.parents)
                self.assertEqual(bob.warnings, [])


class Reg09ValidatorOverlapTests(unittest.TestCase):
    def test_merged_chunk_may_overlap_into_its_last_section(self) -> None:
        """A chunk merged from sections A+B (path A) continues into B (path A > B): valid overlap."""
        blocks = [H("A", 1), Pg(sentences(1, per=6)), H("B", 2), Pg(sentences(14, per=8, prefix="b"))]
        result = ChunkingEngine(SMALL, WordCounter(), strict=True).run(build(blocks), CTX)

        overlapping = [c for c in result.children if c.overlap_prefix]
        self.assertTrue(overlapping)
        self.assertEqual(result.report.problems, [])


class Reg12StaleMetadataTests(unittest.TestCase):
    """A chunk keeping its id and vector must still get fresh metadata (esp. its parent id)."""

    def test_unchanged_chunk_points_at_its_new_parent_after_a_duplicate_is_added(self) -> None:
        for store, parents in stacks(self):
            embedder = FakeEmbedder(dimension=128)
            indexer = IndexingService(embedder, store, parent_store=parents)
            engine = ChunkingEngine(SMALL, WordCounter())
            section = [H("Section 1"), Pg(sentences(3, per=8, prefix="dup"))]
            first = engine.run(build([H("Section 0"), Pg(sentences(3, prefix="z")), *section]), CTX)
            indexer.index(first.children, document_uid="doc-1", parents=first.parents)
            second = engine.run(build([H("Section 0"), Pg(sentences(3, prefix="z")), *section, *section]), CTX)
            report = indexer.index(second.children, document_uid="doc-1", parents=second.parents)

            with self.subTest(store=type(store).__name__):
                self.assertGreaterEqual(report.refreshed, 1)
                keys = [f"{c.document_uid}:{c.parent_id}" for c in second.children]
                self.assertEqual(len(parents.get_many(keys, user_id="u1", course_id="c1")), len(second.parents))
                hits = RetrievalService(embedder, store, parents).search(
                    "dup0_0 dup1_0", user_id="u1", course_id="c1", k=5, assess_relevance=False)
                self.assertEqual(hits.warnings, [])
                self.assertTrue(all(hits.parent_for(h) is not None for h in hits.hits))

    def test_citation_metadata_is_refreshed_when_text_above_shifts_pages(self) -> None:
        store, parents = InMemoryVectorStore(), InMemoryParentStore()
        embedder = FakeEmbedder(dimension=128)
        indexer = IndexingService(embedder, store, parent_store=parents)
        engine = ChunkingEngine(SMALL, WordCounter())
        body = [H("Later"), Pg(sentences(3, prefix="later"))]
        one_page = engine.run(build([H("Early"), Pg(sentences(3)), *body]), CTX)
        indexer.index(one_page.children, document_uid="doc-1", parents=one_page.parents)
        moved = list(body)
        for block in moved:
            block.page_number = 2  # the same text now sits on page 2
        two_pages = engine.run(
            build([H("Early"), Pg(sentences(3)), *moved],
                  pages=[__import__("ai.ingestion.models", fromlist=["PageContent"]).PageContent(page_number=1),
                         __import__("ai.ingestion.models", fromlist=["PageContent"]).PageContent(page_number=2)]),
            CTX)
        report = indexer.index(two_pages.children, document_uid="doc-1", parents=two_pages.parents)

        self.assertEqual(report.embedded, 0)  # the vectors are reused...
        stored = store.query(COLLECTION, embedder.embed_query("later0_0"), user_id="u1", course_id="c1", k=1)[0]
        self.assertEqual(stored.metadata["citation_label"], "p. 2 > Later")  # ...but the citation is current


class Reg13SurrogateTests(unittest.TestCase):
    def test_lone_surrogates_are_replaced_and_never_crash_hashing(self) -> None:
        text = "broken " + chr(0xD800) + " font " + chr(0xDFFF) + " output"

        self.assertEqual(clean_text(text), "broken \ufffd font \ufffd output")
        chunks = ChunkingEngine(SMALL, WordCounter(), strict=True).chunk(build([H("A"), Pg(text * 3)]), CTX)
        self.assertTrue(chunks)


class Reg11UnbreakableTokenTests(unittest.TestCase):
    def test_long_urls_and_blobs_are_cut_to_the_limit(self) -> None:
        counter = ApproxTokenCounter()
        blob = "https://example.com/" + "a1b2c3d4" * 3000
        pieces = TextSplitter(counter).split(blob, 100)

        self.assertTrue(all(counter.count(p) <= 100 for p in pieces))
        self.assertEqual("".join(pieces), blob)

    def test_chunking_a_document_that_contains_a_blob(self) -> None:
        blob = "QUJD" * 20_000
        doc = build([H("Data"), Pg("Before the blob. " + blob + " After the blob.")])
        chunks = ChunkingEngine(tokenizer=ApproxTokenCounter(), strict=True).chunk(doc, CTX)

        self.assertTrue(all(c.token_count <= 480 for c in chunks))
        self.assertEqual("".join(c.text for c in chunks).replace(" ", "").count("QUJD"), 20_000)


class Reg14OfficeTextNormalisationTests(unittest.TestCase):
    """DOCX/PPTX block text used to skip clean_text, so only PDF text was repaired."""

    DIRTY = "efﬁcient cach\u200be\u00a0miss " + chr(0xD800) + " x²"
    CLEAN = "efficient cache miss \ufffd x²"

    def test_docx_paragraphs_lists_and_table_cells(self) -> None:
        import tempfile
        from pathlib import Path

        from docx import Document as NewDocx

        from ai.ingestion.docs_reader import DocxReader
        from tests.pptx_fixtures import FakeOCR

        document = NewDocx()
        document.add_heading(self.DIRTY.replace(chr(0xD800), ""), 1)
        document.add_paragraph(self.DIRTY.replace(chr(0xD800), ""))
        document.add_paragraph(self.DIRTY.replace(chr(0xD800), ""), style="List Bullet")
        table = document.add_table(rows=2, cols=1)
        table.cell(0, 0).text = "head"
        table.cell(1, 0).text = self.DIRTY.replace(chr(0xD800), "")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "dirty.docx"
            document.save(str(path))
            doc = DocxReader(ocr_processor=FakeOCR()).read(path)  # type: ignore[arg-type]

        cleaned = " ".join(self.CLEAN.replace(" \ufffd", "").split())
        texts = [b.text for b in doc.blocks if b.type is not BlockType.TABLE]
        self.assertTrue(texts)
        for text in texts:
            self.assertEqual(text, cleaned)
        self.assertEqual(doc.pages[0].tables[0].rows[1][0], cleaned)

    def test_pptx_titles_bullets_and_chart_free_text(self) -> None:
        from ai.ingestion.pptx_reader import PptxReader
        from tests import pptx_fixtures as fx

        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, self.DIRTY.replace(chr(0xD800), ""), [(self.DIRTY.replace(chr(0xD800), ""), 0)])
        import tempfile

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = fx.save(prs, __import__("pathlib").Path(tmp))
            doc = PptxReader(ocr_processor=fx.FakeOCR()).read(path)  # type: ignore[arg-type]

        cleaned = " ".join(self.CLEAN.replace(" \ufffd", "").split())
        self.assertEqual(doc.metadata["slides"][0]["title"], cleaned)
        self.assertEqual([b.text for b in doc.blocks if b.type is BlockType.LIST_ITEM], [cleaned])


if __name__ == "__main__":
    unittest.main()

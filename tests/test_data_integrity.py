"""Data integrity across the whole stack: ingest -> chunk -> embed -> store -> retrieve.

What goes in must come out unchanged, nothing may be lost or invented, and every stored
record must agree with the object that produced it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

import chromadb
from chromadb.config import Settings
from docx import Document as new_docx

from ai.chunking import ChunkingEngine, IndexingService, collection_name
from ai.chunking.memory_store import InMemoryParentStore, InMemoryVectorStore
from ai.chunking.models import ParentChunk
from ai.ingestion.docs_reader import DocxReader
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.ingestion.models import BlockType
from ai.ingestion.pptx_reader import PptxReader
from ai.retrieval import RetrievalService
from ai.storage import SQLiteParentStore
from ai.vectorstore import ChromaVectorStore
from tests import pdf_fixtures as pf
from tests import pptx_fixtures as fx
from tests.chunk_fixtures import CTX, SMALL, FakeEmbedder, WordCounter
from tests.random_docs import random_document

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "uploads"
COLLECTION = collection_name("fake-embed")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]")


def stacks(test: unittest.TestCase):
    yield "memory", InMemoryVectorStore(), InMemoryParentStore()
    client = chromadb.EphemeralClient(settings=Settings(allow_reset=True, anonymized_telemetry=False))
    client.reset()
    parents = SQLiteParentStore()
    test.addCleanup(client.reset)
    test.addCleanup(parents.close)
    yield "chroma", ChromaVectorStore(client), parents


class StoredRecordIntegrityTests(unittest.TestCase):
    def test_everything_stored_matches_the_chunker_output_for_random_documents(self) -> None:
        engine = ChunkingEngine(SMALL, WordCounter())
        for name, store, parents in stacks(self):
            embedder = FakeEmbedder(dimension=256)
            indexer = IndexingService(embedder, store, parent_store=parents)
            retrieval = RetrievalService(embedder, store, parents)
            for unit, seed in (("page", 11), ("slide", 12), ("document", 13)):
                uid = f"doc-{unit}"
                ctx = CTX.__class__("u1", "c1", uid, "fake-embed")
                result = engine.run(random_document(seed, unit=unit).document, ctx)
                indexer.index(result.children, document_uid=uid, parents=result.parents)

                with self.subTest(stack=name, unit=unit):
                    ids = store.list_ids(COLLECTION, document_uid=uid)
                    self.assertEqual(set(ids), {c.vector_id for c in result.children})
                    self.assertEqual(parents.list_ids(document_uid=uid), {p.store_key for p in result.parents})
                    hashes = store.list_record_hashes(COLLECTION, document_uid=uid)
                    self.assertEqual(hashes, {c.vector_id: c.record_hash for c in result.children})
                    vectors = store.get_embeddings(COLLECTION, list(ids))
                    for child in result.children:
                        want = embedder.embed_documents([child.embedding_text])[0]
                        for a, b in zip(vectors[child.vector_id], want, strict=True):
                            self.assertAlmostEqual(a, b, places=5)
                    # every child's parent reference resolves, within its own scope
                    found = parents.get_many([f"{c.document_uid}:{c.parent_id}" for c in result.children],
                                             user_id="u1", course_id="c1")
                    self.assertEqual(len(found), len(result.parents))
                    for parent in result.parents:
                        self.assertEqual(found[parent.store_key], parent)

                    # self-retrieval: searching with a chunk's own text finds that chunk
                    misses = []
                    for child in result.children:
                        if child.kind == "table":
                            continue  # embedded as "Header: value" text; covered by the table test below
                        hits = retrieval.search(child.text[:4000], user_id="u1", course_id="c1", k=5,
                                                document_uids=[uid], expand_parents=False).hits
                        if child.chunk_id not in {h.chunk_id for h in hits}:
                            misses.append(child.chunk_id)
                    self.assertEqual(misses, [], "chunks that cannot be found by their own text")

    def test_every_table_row_is_found_by_its_own_header_value_pairs(self) -> None:
        """Tables are embedded as 'Header: value' lines, so that is how users' questions match."""
        engine = ChunkingEngine(SMALL, WordCounter())
        for name, store, parents in stacks(self):
            embedder = FakeEmbedder(dimension=256)
            indexer = IndexingService(embedder, store, parent_store=parents)
            retrieval = RetrievalService(embedder, store, parents)
            result = engine.run(random_document(11, unit="page").document, CTX)
            indexer.index(result.children, document_uid=CTX.document_uid, parents=result.parents)
            tables = [c for c in result.children if c.kind == "table"]
            self.assertTrue(tables)

            with self.subTest(stack=name):
                for chunk in tables:
                    body = [ln for ln in chunk.embedding_text.splitlines() if re.match(r"^H\d: t\d+r\d+c\d", ln)]
                    query = " ".join(body[:8])
                    hits = retrieval.search(query, user_id="u1", course_id="c1", k=5, expand_parents=False).hits
                    self.assertIn(chunk.chunk_id, {h.chunk_id for h in hits})

    def test_all_outputs_are_json_serialisable(self) -> None:
        engine = ChunkingEngine(SMALL, WordCounter())
        for unit in ("page", "slide", "document"):
            result = engine.run(random_document(21, unit=unit).document, CTX)
            for child in result.children:
                json.dumps(child.chroma_metadata())
                json.dumps(child.to_chroma_record())
            for parent in result.parents:
                json.dumps(parent.to_dict())
                json.dumps(parent.to_record())
                self.assertEqual(ParentChunk.from_dict(json.loads(json.dumps(parent.to_dict()))), parent)


class DocumentConsistencyTests(unittest.TestCase):
    """Statistics, identity and block structure agree with each other for every format."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        ocr = fx.FakeOCR()
        self.pipeline = IngestionPipeline(
            docx_reader=DocxReader(ocr_processor=ocr),  # type: ignore[arg-type]
            pptx_reader=PptxReader(ocr_processor=ocr),  # type: ignore[arg-type]
        )

    def documents(self):
        pdf = pf.make_pdf(self.dir / "a.pdf", [[("Heading", 20.0), *pf.body()], pf.body("second page")])
        document = new_docx()
        document.add_heading("Title", 1)
        document.add_paragraph("Body text.")
        document.add_paragraph("item", style="List Bullet")
        table = document.add_table(rows=2, cols=2)
        for r in range(2):
            for c in range(2):
                table.cell(r, c).text = f"r{r}c{c}"
        docx = self.dir / "a.docx"
        document.save(str(docx))
        prs = fx.blank_presentation()
        fx.add_bullet_slide(prs, "Lecture", [("Main", 0), ("Sub", 1)])
        fx.add_chart_slide(prs, "Chart")
        pptx = fx.save(prs, self.dir, "a.pptx")
        return [(pdf, "pdf"), (docx, "docx"), (pptx, "pptx")]

    def test_identity_fields_are_truthful(self) -> None:
        for path, kind in self.documents():
            with self.subTest(kind=kind):
                doc = self.pipeline.ingest(path)
                source = doc.source
                assert source is not None
                self.assertEqual(source.sha256, hashlib.sha256(path.read_bytes()).hexdigest())
                self.assertEqual(source.doc_id, source.sha256[:16])
                self.assertEqual(source.file_size_bytes, path.stat().st_size)
                self.assertEqual((source.file_name, source.file_type), (path.name, kind))
                self.assertEqual(source.page_count, len(doc.pages))
                parsed = dt.datetime.fromisoformat(source.ingested_at)
                self.assertIsNotNone(parsed.tzinfo)
                self.assertEqual(doc.metadata["schema_version"], doc.schema_version)

    def test_statistics_agree_with_the_blocks(self) -> None:
        for path, kind in self.documents():
            with self.subTest(kind=kind):
                doc = self.pipeline.ingest(path)
                stats, blocks = doc.statistics, doc.blocks
                self.assertEqual(stats["block_count"], len(blocks))
                self.assertEqual(stats["page_count"], len(doc.pages))
                self.assertEqual(stats["heading_count"], sum(b.type is BlockType.HEADING for b in blocks))
                self.assertEqual(stats["list_item_count"], sum(b.type is BlockType.LIST_ITEM for b in blocks))
                self.assertEqual(stats["table_count"], sum(len(p.tables) for p in doc.pages))
                self.assertEqual(stats["total_characters"], sum(len(p.final_text) for p in doc.pages))
                self.assertTrue(0.0 <= stats["average_confidence"] <= 1.0)
                self.assertTrue(all(1 <= n <= len(doc.pages) for n in stats["low_confidence_pages"]))

    def test_block_structure_is_internally_consistent(self) -> None:
        for path, kind in self.documents():
            with self.subTest(kind=kind):
                doc = self.pipeline.ingest(path)
                blocks = doc.blocks
                self.assertEqual([b.order for b in blocks], list(range(len(blocks))))
                numbers = {p.page_number for p in doc.pages}
                titles_seen: list[str] = []
                for block in blocks:
                    self.assertIn(block.page_number, numbers)
                    self.assertTrue(block.text.strip())
                    if block.type is BlockType.HEADING:
                        self.assertEqual(block.heading_path[-1], block.text)
                        titles_seen.append(block.text)
                    else:
                        for title in block.heading_path:
                            self.assertIn(title, titles_seen)  # a path only names headings that came before

    def test_chunks_trace_back_to_real_blocks_and_pages(self) -> None:
        engine = ChunkingEngine(tokenizer=WordCounter(), strict=True)
        for path, kind in self.documents():
            with self.subTest(kind=kind):
                doc = self.pipeline.ingest(path)
                orders = {b.order for b in doc.blocks}
                result = engine.run(doc, CTX)
                pages = {p.page_number for p in doc.pages}
                for chunk in [*result.children, *result.parents]:
                    self.assertTrue(set(chunk.block_orders) <= orders)
                    self.assertTrue({chunk.page_start, chunk.page_end} <= pages)
                    self.assertTrue(chunk.citation_label)
                    self.assertEqual((chunk.file_type, chunk.sha256), (kind, doc.source.sha256))


@unittest.skipUnless((SAMPLES / "test2.pdf").exists() and (SAMPLES / "test.pdf").exists(), "samples missing")
class RealDocumentCleanlinessTests(unittest.TestCase):
    def test_real_pdfs_produce_clean_chunks(self) -> None:
        pipeline = IngestionPipeline()
        engine = ChunkingEngine(tokenizer=WordCounter(), strict=True)
        for name in ("test.pdf", "test2.pdf"):
            with self.subTest(sample=name):
                doc = pipeline.ingest(SAMPLES / name)
                result = engine.run(doc, CTX)
                self.assertTrue(result.children)
                ids = [c.chunk_id for c in result.children]
                self.assertEqual(len(ids), len(set(ids)))
                for chunk in result.children:
                    self.assertTrue(chunk.text.strip())
                    self.assertIsNone(CONTROL.search(chunk.text), f"control/replacement char in {name}")
                    self.assertNotRegex(chunk.text, r"\[(Page|Slide) \d+\]")  # location markers are not content
                    self.assertGreater(chunk.page_start, 0)

    def test_text_is_not_silently_altered_by_the_stack(self) -> None:
        """Every word the extractor produced for a page is present in that page's chunks."""
        doc = IngestionPipeline().ingest(SAMPLES / "test2.pdf")
        result = ChunkingEngine(tokenizer=WordCounter()).run(doc, CTX)
        chunked = " ".join(c.text for c in result.children)
        for block in doc.blocks:
            if block.type in (BlockType.PARAGRAPH, BlockType.LIST_ITEM):
                for word in re.findall(r"[A-Za-z]{6,}", block.text):
                    self.assertIn(word, chunked)


if __name__ == "__main__":
    unittest.main()

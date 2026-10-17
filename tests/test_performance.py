"""Performance and scalability budgets.

Budgets are deliberately generous (CI machines vary); they exist to catch order-of-magnitude
regressions and accidental quadratic behaviour, not to benchmark. Set
``INTELLISTUDY_SKIP_SLOW=1`` to skip the slower tests. Timings are printed at the end.
"""

from __future__ import annotations

import os
import statistics
import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path

import chromadb
from chromadb.config import Settings
from docx import Document as new_docx

from ai.chunking import ChunkingEngine, IndexingService, InMemoryVectorStore
from ai.chunking.memory_store import InMemoryParentStore
from ai.ingestion.docs_reader import DocxReader
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.ingestion.pptx_reader import PptxReader
from ai.retrieval import RetrievalService
from ai.storage import SQLiteParentStore
from ai.vectorstore import ChromaVectorStore
from tests import pdf_fixtures as pf
from tests import pptx_fixtures as fx
from tests.chunk_fixtures import CTX, FakeEmbedder, H, Pg, WordCounter, build
from tests.random_docs import random_document

SLOW = unittest.skipIf(os.environ.get("INTELLISTUDY_SKIP_SLOW") == "1", "INTELLISTUDY_SKIP_SLOW=1")
TIMINGS: dict[str, str] = {}


def tearDownModule() -> None:
    if TIMINGS:
        width = max(len(k) for k in TIMINGS)
        print("\n--- performance summary ---")
        for name, value in sorted(TIMINGS.items()):
            print(f"{name:<{width}}  {value}")


def timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


def big_blocks(total_words: int, section_words: int = 400):
    blocks, n = [], 0
    for s in range(total_words // section_words):
        words = " ".join(f"w{s}_{i}" + ("." if i % 12 == 11 else "") for i in range(section_words))
        blocks += [H(f"Section {s}", 1 + s % 3), Pg(words)]
        n += section_words
    return blocks


class ChunkingPerformance(unittest.TestCase):
    def test_throughput_on_a_very_large_document(self) -> None:
        doc = build(big_blocks(200_000))
        engine = ChunkingEngine(tokenizer=WordCounter(), strict=True)
        result, seconds = timed(lambda: engine.run(doc, CTX))
        TIMINGS["chunk 200k words"] = f"{seconds:.2f}s -> {len(result.children)} chunks"

        self.assertLess(seconds, 20.0)
        self.assertGreater(len(result.children), 400)

    def test_cost_grows_roughly_linearly_with_input_size(self) -> None:
        """A quadratic step (e.g. repeated list scans) would make 4x input cost ~16x."""
        engine = ChunkingEngine(tokenizer=WordCounter())
        small, big = build(big_blocks(30_000)), build(big_blocks(120_000))
        engine.run(small, CTX)  # warm-up
        _, t_small = timed(lambda: engine.run(small, CTX))
        _, t_big = timed(lambda: engine.run(big, CTX))
        ratio = t_big / max(t_small, 1e-3)
        TIMINGS["chunk scaling 4x input"] = f"{ratio:.1f}x time ({t_small:.2f}s -> {t_big:.2f}s)"

        self.assertLess(ratio, 9.0, f"4x input took {ratio:.1f}x as long: superlinear growth")

    def test_peak_memory_is_bounded(self) -> None:
        doc = build(big_blocks(100_000))
        engine = ChunkingEngine(tokenizer=WordCounter())
        tracemalloc.start()
        engine.run(doc, CTX)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        TIMINGS["chunk 100k words peak mem"] = f"{peak / 1e6:.0f} MB"

        self.assertLess(peak, 600e6)

    def test_many_random_documents(self) -> None:
        engine = ChunkingEngine(tokenizer=WordCounter(), strict=True)
        _, seconds = timed(lambda: [engine.run(random_document(s, unit=u).document, CTX)
                                    for s in range(25) for u in ("page", "slide", "document")])
        TIMINGS["chunk 75 random docs"] = f"{seconds:.2f}s"

        self.assertLess(seconds, 30.0)


class IndexingPerformance(unittest.TestCase):
    @staticmethod
    def many_chunks(n_sections: int):
        blocks = []
        for s in range(n_sections):
            blocks += [H(f"S{s}"), Pg(" ".join(f"u{s}_{i}" for i in range(60)) + ".")]
        return ChunkingEngine(tokenizer=WordCounter()).run(build(blocks), CTX)

    def stack(self, kind: str):
        if kind == "memory":
            return InMemoryVectorStore(), InMemoryParentStore()
        client = chromadb.EphemeralClient(settings=Settings(allow_reset=True, anonymized_telemetry=False))
        client.reset()
        parents = SQLiteParentStore()
        self.addCleanup(client.reset)
        self.addCleanup(parents.close)
        return ChromaVectorStore(client), parents

    def run_kind(self, kind: str, sections: int, budget: float) -> None:
        chunk_set = self.many_chunks(sections)
        store, parents = self.stack(kind)
        embedder = FakeEmbedder(dimension=64)
        service = IndexingService(embedder, store, parent_store=parents, batch_size=128)
        first, t_first = timed(lambda: service.index(chunk_set.children, document_uid=CTX.document_uid,
                                                     parents=chunk_set.parents))
        again, t_again = timed(lambda: service.index(chunk_set.children, document_uid=CTX.document_uid,
                                                     parents=chunk_set.parents))
        TIMINGS[f"index {len(chunk_set.children)} chunks ({kind})"] = f"{t_first:.2f}s; no-op re-ingest {t_again:.2f}s"

        self.assertEqual(first.embedded, len(chunk_set.children))
        self.assertEqual((again.embedded, again.reused, again.deleted, again.refreshed), (0, 0, 0, 0))
        self.assertLess(t_first, budget)
        self.assertLess(t_again, budget / 2)

    def test_memory_store_3000_chunks(self) -> None:
        self.run_kind("memory", 3000, 15.0)

    @SLOW
    def test_chroma_3000_chunks(self) -> None:
        self.run_kind("chroma", 3000, 90.0)


@SLOW
class RetrievalLatency(unittest.TestCase):
    def test_query_latency_over_5000_vectors(self) -> None:
        client = chromadb.EphemeralClient(settings=Settings(allow_reset=True, anonymized_telemetry=False))
        client.reset()
        self.addCleanup(client.reset)
        store, parents = ChromaVectorStore(client), SQLiteParentStore()
        self.addCleanup(parents.close)
        embedder = FakeEmbedder(dimension=64)
        blocks = []
        for s in range(5000):
            blocks += [H(f"S{s}"), Pg(" ".join(f"k{s}_{i}" for i in range(50)) + ".")]
        chunk_set = ChunkingEngine(tokenizer=WordCounter()).run(build(blocks), CTX)
        IndexingService(embedder, store, parent_store=parents, batch_size=256).index(
            chunk_set.children, document_uid=CTX.document_uid, parents=chunk_set.parents)
        service = RetrievalService(embedder, store, parents)

        times = []
        for q in range(60):
            _, dt = timed(lambda q=q: service.search(f"k{q * 70}_3 k{q * 70}_9", user_id="u1", course_id="c1", k=5))
            times.append(dt)
        p95 = sorted(times)[int(len(times) * 0.95) - 1]
        TIMINGS["retrieve over 5000 vectors"] = f"mean {statistics.mean(times) * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms"

        self.assertLess(statistics.mean(times), 0.25)
        self.assertLess(p95, 0.6)


@SLOW
class IngestionPerformance(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        ocr = fx.FakeOCR()
        self.pipeline = IngestionPipeline(
            docx_reader=DocxReader(ocr_processor=ocr),  # type: ignore[arg-type]
            pptx_reader=PptxReader(ocr_processor=ocr),  # type: ignore[arg-type]
        )

    def test_150_page_pdf(self) -> None:
        pages = [[(f"Chapter {n}", 20.0), *pf.body(f"Unique marker {n} here for the page.")] for n in range(150)]
        path = pf.make_pdf(self.dir / "big.pdf", pages, start_y=200.0)
        doc, seconds = timed(lambda: self.pipeline.ingest(path))
        TIMINGS["ingest 150-page PDF"] = f"{seconds:.1f}s"

        self.assertEqual(len(doc.pages), 150)
        self.assertLess(seconds, 90.0)

    def test_3000_paragraph_docx(self) -> None:
        document = new_docx()
        for i in range(3000):
            document.add_paragraph(f"Paragraph {i} with filler words to make it a realistic length sentence.")
        path = self.dir / "big.docx"
        document.save(str(path))
        doc, seconds = timed(lambda: self.pipeline.ingest(path))
        TIMINGS["ingest 3000-paragraph DOCX"] = f"{seconds:.1f}s"

        self.assertEqual(doc.statistics["paragraph_count"], 3000)
        self.assertLess(seconds, 45.0)

    def test_150_slide_pptx(self) -> None:
        prs = fx.blank_presentation()
        for i in range(150):
            fx.add_bullet_slide(prs, f"Slide {i}", [(f"Point {i}", 0), ("Detail", 1)])
        path = fx.save(prs, self.dir, "big.pptx")
        doc, seconds = timed(lambda: self.pipeline.ingest(path))
        TIMINGS["ingest 150-slide PPTX"] = f"{seconds:.1f}s"

        self.assertEqual(doc.statistics["page_count"], 150)
        self.assertLess(seconds, 45.0)


@unittest.skipUnless(os.environ.get("INTELLISTUDY_MODEL_TESTS") == "1", "set INTELLISTUDY_MODEL_TESTS=1")
class RealModelPerformance(unittest.TestCase):
    def test_bge_embeds_100_chunks_on_cpu(self) -> None:
        from ai.embedding import BgeEmbedder

        embedder = BgeEmbedder()
        embedder.embed_documents(["warm up"])
        texts = [" ".join(f"word{i}_{n}" for i in range(300)) for n in range(100)]
        vectors, seconds = timed(lambda: embedder.embed_documents(texts))
        TIMINGS["BGE 100 x ~300-token chunks (CPU)"] = f"{seconds:.1f}s"

        self.assertEqual(len(vectors), 100)
        self.assertLess(seconds, 180.0)


if __name__ == "__main__":
    unittest.main()

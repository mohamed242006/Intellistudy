"""Build (or reuse) a persistent index of the evaluation corpus: ingest -> chunk -> BGE -> Chroma + SQLite.

The index lives in a directory with a ``manifest.json`` that records the chunker version, the embedding
model and the sha256 of every file. If any of them changed the index is rebuilt from scratch, so results are
always produced against the current code.

    python -m evaluation.index_builder --index-dir evaluation/.index
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path

from ai.chunking import EMBEDDING_MODEL, ChunkContext, ChunkingEngine, IndexingService, default_token_counter
from ai.chunking.config import CHUNKER_VERSION
from ai.embedding import BgeEmbedder
from ai.ingestion.ingestion_pipeline import IngestionPipeline
from ai.storage import SQLiteParentStore
from ai.vectorstore import ChromaVectorStore
from evaluation.retrieval_dataset import EXCLUDED_FILES

USER = "eval"
COURSE = "eval"
SUFFIXES = {".pdf", ".docx", ".pptx"}

logger = logging.getLogger(__name__)


def corpus_files(root: Path = Path("data/uploads")) -> list[Path]:
    files = [
        p
        for p in sorted(root.rglob("*"))
        if p.suffix.lower() in SUFFIXES and not any(skip in p.name for skip in EXCLUDED_FILES)
    ]
    unique: dict[str, Path] = {}
    for path in files:  # the same file stored twice would split every hit between two documents
        if path.stat().st_size > 0:
            unique.setdefault(_sha(path), path)
    return list(unique.values())


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _manifest(files: list[Path]) -> dict:
    return {
        "chunker_version": CHUNKER_VERSION,
        "embedding_model": EMBEDDING_MODEL,
        "files": {str(p.as_posix()): _sha(p) for p in files},
    }


def open_stores(index_dir: Path) -> tuple[ChromaVectorStore, SQLiteParentStore]:
    return ChromaVectorStore(path=index_dir / "chroma"), SQLiteParentStore(index_dir / "parents.sqlite3")


def build_index(index_dir: Path, *, force: bool = False, root: Path = Path("data/uploads")) -> dict:
    """Return the manifest of an up-to-date index, building it first when needed."""
    files = corpus_files(root)
    wanted = _manifest(files)
    manifest_path = index_dir / "manifest.json"
    if not force and manifest_path.exists():
        current = json.loads(manifest_path.read_text(encoding="utf-8"))
        if {k: current.get(k) for k in wanted} == wanted:
            return current
    shutil.rmtree(index_dir, ignore_errors=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    if any(index_dir.iterdir()):
        raise RuntimeError(
            f"{index_dir} could not be cleared (a file is locked, often by a cloud-sync client such as OneDrive). "
            "Pause syncing or pass --index-dir with a folder outside the synced tree."
        )

    store, parents = open_stores(index_dir)
    indexer = IndexingService(BgeEmbedder(), store, parent_store=parents)
    engine = ChunkingEngine(tokenizer=default_token_counter(), strict=False)
    pipeline = IngestionPipeline()
    uids: dict[str, str] = {}
    counts: dict[str, int] = {}
    for path in files:
        started = time.time()
        document = pipeline.ingest(path)
        uid = "up-" + document.source.doc_id
        chunks = engine.run(document, ChunkContext(USER, COURSE, uid, EMBEDDING_MODEL))
        indexer.index(chunks.children, document_uid=uid, parents=chunks.parents)
        uids[path.name] = uid
        counts[path.name] = len(chunks.children)
        print(f"indexed {path.name}: {len(chunks.children)} chunks in {time.time() - started:.1f}s", flush=True)
    result = {**wanted, "document_uids": uids, "chunk_counts": counts}
    manifest_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> None:
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-dir", type=Path, default=Path("evaluation/.index"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest = build_index(args.index_dir, force=args.force)
    print("index ready:", sum(manifest["chunk_counts"].values()), "chunks in", len(manifest["chunk_counts"]), "files")


if __name__ == "__main__":
    main()

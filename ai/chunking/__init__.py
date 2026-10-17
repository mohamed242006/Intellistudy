"""IntelliStudy chunking layer: ``Document`` (schema 2.x) -> parent/child chunks -> vector store.

Typical use::

    engine = ChunkingEngine(tokenizer=default_token_counter())
    chunk_set = engine.run(document, ChunkContext(user_id, course_id, document_uid, EMBEDDING_MODEL))
    IndexingService(embedder, store).index(chunk_set.children, document_uid=document_uid)
"""

from ai.chunking.config import (
    CHUNKER_VERSION,
    EMBEDDING_MODEL,
    ChunkConfig,
    collection_name,
)
from ai.chunking.engine import ChunkingEngine
from ai.chunking.errors import ChunkingError, ChunkValidationError, IndexingError
from ai.chunking.indexing import IndexingService, IndexReport, ReingestPlan, ReingestPlanner
from ai.chunking.interfaces import Embedder, ScoredRecord, VectorRecord, VectorStore
from ai.chunking.memory_store import InMemoryVectorStore
from ai.chunking.models import ChildChunk, Chunk, ChunkContext, ChunkReport, ChunkSet, ParentChunk
from ai.chunking.tokens import ApproxTokenCounter, HFTokenCounter, TokenCounter, default_token_counter

__all__ = [
    "CHUNKER_VERSION",
    "EMBEDDING_MODEL",
    "ApproxTokenCounter",
    "ChildChunk",
    "Chunk",
    "ChunkConfig",
    "ChunkContext",
    "ChunkReport",
    "ChunkSet",
    "ChunkValidationError",
    "ChunkingEngine",
    "ChunkingError",
    "Embedder",
    "HFTokenCounter",
    "InMemoryVectorStore",
    "IndexReport",
    "IndexingError",
    "IndexingService",
    "ParentChunk",
    "ReingestPlan",
    "ReingestPlanner",
    "ScoredRecord",
    "TokenCounter",
    "VectorRecord",
    "VectorStore",
    "collection_name",
    "default_token_counter",
]

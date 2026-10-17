"""Exceptions raised by the chunking layer."""

from __future__ import annotations


class ChunkingError(Exception):
    """The document cannot be chunked (unsupported schema, missing source info, ...)."""


class ChunkValidationError(ChunkingError):
    """Chunking produced output that violates the design invariants (strict mode)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        shown = "; ".join(problems[:5])
        extra = f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""
        super().__init__(f"{len(problems)} chunk invariant(s) violated: {shown}{extra}")


class IndexingError(Exception):
    """Embedding or vector-store indexing could not be performed consistently."""


class EmbeddingError(IndexingError):
    """The embedding model failed or returned vectors of the wrong shape."""

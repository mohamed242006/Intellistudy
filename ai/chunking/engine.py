"""ChunkingEngine: the public entry point of the chunking layer.

Composition (every collaborator is injectable, which keeps the engine open for
extension and closed for modification):

    BlockSelector -> build_sections -> ChunkBuilder (AtomBuilder, TextSplitter)
                  -> ParentBuilder -> ChunkValidator

The engine knows nothing about embedding models or vector databases.
"""

from __future__ import annotations

import logging

from ai.chunking.atoms import AtomBuilder
from ai.chunking.builder import ChunkBuilder
from ai.chunking.config import ChunkConfig
from ai.chunking.errors import ChunkingError, ChunkValidationError
from ai.chunking.models import ChildChunk, ChunkContext, ChunkReport, ChunkSet
from ai.chunking.parents import ParentBuilder
from ai.chunking.sections import build_sections
from ai.chunking.selection import BlockSelector
from ai.chunking.text import TextSplitter
from ai.chunking.tokens import ApproxTokenCounter, TokenCounter
from ai.chunking.validation import ChunkValidator
from ai.ingestion.models import Document

logger = logging.getLogger(__name__)

SUPPORTED_SCHEMA_MAJOR = "2"


class ChunkingEngine:
    """Turns a canonical :class:`Document` into parent and child chunks.

    A pure function of ``(document, ctx, config, tokenizer)``: no I/O, no randomness,
    so identical input yields identical output (re-ingestion relies on this).

    Args:
        config: chunking parameters (final defaults: 400 / 480 / 60 tokens).
        tokenizer: any :class:`TokenCounter`; use the embedding model's own tokenizer.
        strict: raise :class:`ChunkValidationError` if the result violates an invariant;
            otherwise the problems are logged and stored on ``report.problems``.
    """

    def __init__(
        self,
        config: ChunkConfig | None = None,
        tokenizer: TokenCounter | None = None,
        *,
        selector: BlockSelector | None = None,
        builder: ChunkBuilder | None = None,
        parent_builder: ParentBuilder | None = None,
        validator: ChunkValidator | None = None,
        strict: bool = False,
    ) -> None:
        self.config = config or ChunkConfig()
        self.tokenizer: TokenCounter = tokenizer or ApproxTokenCounter()
        splitter = TextSplitter(self.tokenizer)
        self.selector = selector or BlockSelector(self.config)
        self.builder = builder or ChunkBuilder(
            self.config, self.tokenizer, AtomBuilder(self.config, self.tokenizer, splitter), splitter
        )
        self.parent_builder = parent_builder or ParentBuilder(self.config, self.tokenizer)
        self.validator = validator or ChunkValidator(self.config, self.selector)
        self.strict = strict

    # ------------------------------------------------------------------ API
    def run(self, document: Document, ctx: ChunkContext) -> ChunkSet:
        """Chunk ``document``; returns parents, children and a report."""
        self._check_document(document)
        report = ChunkReport()
        blocks = self.selector.select(document, report)
        sections = build_sections(blocks, document.unit)
        children = self.builder.build(sections, document, ctx, report)
        parents, children = self.parent_builder.build(children)
        report.chunk_count, report.parent_count = len(children), len(parents)

        problems = self.validator.validate(document, children, parents, ctx=ctx, report=report)
        report.problems = problems
        if problems:
            logger.error("Chunking invariants violated for %s: %s", document.source_path, problems[:5])
            if self.strict:
                raise ChunkValidationError(problems)
        return ChunkSet(parents=parents, children=children, report=report)

    def chunk(self, document: Document, ctx: ChunkContext) -> list[ChildChunk]:
        """Just the retrievable (child) chunks."""
        return self.run(document, ctx).children

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _check_document(document: Document) -> None:
        if document.source is None:
            raise ChunkingError("Document.source is required for chunking (ingest with the pipeline)")
        major = str(document.schema_version).split(".")[0]
        if major != SUPPORTED_SCHEMA_MAJOR:
            raise ChunkingError(
                f"Unsupported document schema {document.schema_version!r}; "
                f"this chunker reads schema {SUPPORTED_SCHEMA_MAJOR}.x"
            )

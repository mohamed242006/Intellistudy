"""Context Builder: turn a ``RetrievalResult`` into the numbered sources the model may use.

Rules
    * hits are kept in retrieval order and tagged ``S1..Sn``; the tag is what the model cites and what we validate;
    * identical passages are listed once (the same slide repeated, a duplicated paragraph);
    * a token budget bounds the context; the best hit is always kept, lower ranked ones are dropped first;
    * for the top few sources the wider section (the parent chunk) is attached when it is small enough, so the
      model sees the surrounding sentences without the prompt growing unbounded;
    * model-generated text (a figure description) is marked ``generated`` so the answer can be hedged.
"""

from __future__ import annotations

import re

from ai.answering.models import ContextBundle, SourceRef
from ai.chunking.tokens import ApproxTokenCounter, TokenCounter
from ai.retrieval.models import RetrievalResult, RetrievedChunk

_SPACES = re.compile(r"\s+")
GENERATED_MARKER = "Generated description"


def _norm(text: str) -> str:
    return _SPACES.sub(" ", text).strip().casefold()


class ContextBuilder:
    def __init__(
        self,
        counter: TokenCounter | None = None,
        *,
        max_context_tokens: int = 3500,
        max_sources: int = 6,
        parent_context: bool = True,
        parent_tokens: int = 350,
        parent_sources: int = 2,
    ) -> None:
        self._counter = counter or ApproxTokenCounter()
        self._max_tokens = max_context_tokens
        self._max_sources = max_sources
        self._parent_context = parent_context
        self._parent_tokens = parent_tokens
        self._parent_sources = parent_sources

    def build(self, question: str, result: RetrievalResult) -> ContextBundle:
        sources: list[SourceRef] = []
        seen: set[str] = set()
        used = 0
        omitted = 0
        warnings: list[str] = []
        for hit in result.hits:
            key = _norm(hit.text)
            if key in seen:
                omitted += 1
                continue
            cost = self._counter.count(hit.text)
            if sources and (len(sources) >= self._max_sources or used + cost > self._max_tokens):
                omitted += 1
                continue
            context = ""
            if self._parent_context and len(sources) < self._parent_sources:
                context = self._wider(result, hit, cost, used)
            used += cost + (self._counter.count(context) if context else 0)
            seen.add(key)
            sources.append(self._source(f"S{len(sources) + 1}", hit, context))
        if omitted:
            warnings.append(f"{omitted} retrieved passage(s) left out (duplicates or context budget)")
        return ContextBundle(question=question, sources=tuple(sources), tokens=used, omitted=omitted, warnings=tuple(warnings))

    # ------------------------------------------------------------------ helpers
    def _wider(self, result: RetrievalResult, hit: RetrievedChunk, cost: int, used: int) -> str:
        parent = result.parent_for(hit)
        if parent is None:
            return ""
        text = parent.parent.text
        extra = self._counter.count(text)
        if _norm(text) == _norm(hit.text) or extra > self._parent_tokens or used + cost + extra > self._max_tokens:
            return ""
        return text

    @staticmethod
    def _source(tag: str, hit: RetrievedChunk, context: str) -> SourceRef:
        return SourceRef(
            tag=tag,
            chunk_id=hit.chunk_id,
            document_uid=hit.document_uid,
            file_name=hit.file_name,
            citation_label=hit.citation_label,
            page_number=hit.page_number,
            slide_number=hit.slide_number,
            kind=hit.kind,
            text=hit.text,
            score=hit.rerank_score if hit.rerank_score is not None else hit.score,
            ocr_confidence=hit.ocr_confidence,
            low_confidence=hit.low_confidence,
            generated=GENERATED_MARKER in hit.text,
            figure_label=str(hit.metadata.get("figure_label", "")),
            context=context,
        )

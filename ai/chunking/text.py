"""Sentence-aware text splitting and overlap extraction (token-budgeted)."""

from __future__ import annotations

import re

from ai.chunking.tokens import TokenCounter

_SENTENCE = re.compile(r"(?<=[.!?;\u061f])\s+|\n+")


class TextSplitter:
    """Splits text at sentence boundaries without ever exceeding a token limit."""

    def __init__(self, counter: TokenCounter) -> None:
        self._counter = counter

    def count(self, text: str) -> int:
        return self._counter.count(text)

    def sentences(self, text: str) -> list[str]:
        return [s.strip() for s in _SENTENCE.split(text) if s and s.strip()]

    def split(self, text: str, limit: int) -> list[str]:
        """Pieces of at most ``limit`` tokens, cut between sentences (words as last resort)."""
        pieces: list[str] = []
        current: list[str] = []
        used = 0

        def flush() -> None:
            nonlocal used
            if current:
                pieces.append(" ".join(current))
                current.clear()
                used = 0

        for sentence in self.sentences(text):
            tokens = self.count(sentence)
            if tokens > limit:
                flush()
                pieces.extend(self._split_words(sentence, limit))
                continue
            if current and used + tokens > limit:
                flush()
            current.append(sentence)
            used += tokens
        flush()
        return pieces

    def _split_words(self, sentence: str, limit: int) -> list[str]:
        pieces: list[str] = []
        current: list[str] = []
        for word in sentence.split():
            if self.count(word) > limit:  # unbreakable token: base64, long URL, minified code
                if current:
                    pieces.append(" ".join(current))
                    current = []
                pieces.extend(self._split_chars(word, limit))
                continue
            if current and self.count(" ".join([*current, word])) > limit:
                pieces.append(" ".join(current))
                current = []
            current.append(word)
        if current:
            pieces.append(" ".join(current))
        return pieces

    def _split_chars(self, word: str, limit: int) -> list[str]:
        """Cut one over-long token into slices of at most ``limit`` tokens."""
        pieces: list[str] = []
        rest = word
        while rest:
            size = max(1, len(rest) * limit // max(self.count(rest), 1))
            while size > 1 and self.count(rest[:size]) > limit:
                size = max(1, size * 3 // 4)  # estimate was too generous: shrink until it fits
            pieces.append(rest[:size])
            rest = rest[size:]
        return pieces

    def tail(self, text: str, limit: int) -> str:
        """Last whole sentences of ``text`` totalling at most ``limit`` tokens."""
        if limit <= 0:
            return ""
        picked: list[str] = []
        used = 0
        for sentence in reversed(self.sentences(text)):
            tokens = self.count(sentence)
            if used + tokens > limit:
                break
            picked.append(sentence)
            used += tokens
        return " ".join(reversed(picked))

"""Detect bibliography chunks and queries that are really asking for bibliographic information.

A reference list repeats the title words of every cited paper, so it matches topic queries strongly
("almost Gorenstein ring" -> the References page, ahead of the abstract). It is useful only when the
user asks about sources, so by default such chunks are ranked after the body text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_REFERENCE_TITLES = frozenset(
    {"references", "reference", "bibliography", "works cited", "literature cited", "sources", "citations"}
)
_NUMBERED_ENTRY = re.compile(r"^\s*\[\d{1,3}\]\s*\S")
_TITLE_CLEAN = re.compile(r"[^a-z ]+")
_INTENT = re.compile(
    r"\b(references?|bibliograph\w*|cited?|cites|citations?|who (?:wrote|authored)|authors?|published|"
    r"journal|doi|et al|paper by|papers by|which papers|sources?)\b",
    re.IGNORECASE,
)


def _title_key(text: str) -> str:
    return " ".join(_TITLE_CLEAN.sub(" ", text.lower()).split())


def is_reference_section(heading_path: Sequence[str], text: str = "") -> bool:
    """True for a bibliography: a heading named References/Bibliography/... or mostly ``[n] Author`` lines."""
    if any(_title_key(part) in _REFERENCE_TITLES for part in heading_path):
        return True
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    numbered = sum(1 for line in lines if _NUMBERED_ENTRY.match(line))
    return numbered / len(lines) >= 0.5


def asks_for_references(query: str) -> bool:
    """True when the query is about authors, citations or sources rather than the subject itself."""
    return bool(_INTENT.search(query))

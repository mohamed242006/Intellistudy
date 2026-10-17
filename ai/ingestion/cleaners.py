"""Text cleaning helpers.

``clean_text`` normalises extracted text *without* destroying meaning that
study material depends on: superscripts / subscripts, vulgar fractions,
double-struck number sets, scientific notation and hyphenated compounds all
survive. Only presentation artefacts (ligatures, full-width forms, stray
control characters, soft wraps) are repaired.
"""

from __future__ import annotations

import re
import unicodedata

_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}
_MULTI_SPACE = re.compile(r"[ \t\u00a0]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Zero-width space, word joiner and BOM are layout artefacts; ZWJ/ZWNJ (U+200C/U+200D) are
# kept because Arabic and Indic scripts need them for correct shaping.
_INVISIBLE = re.compile("[" + chr(0x200B) + chr(0x2060) + chr(0xFEFF) + "]")
# Lone UTF-16 surrogates (from broken PDF fonts) cannot be encoded as UTF-8 and would crash
# hashing, embedding and storage downstream; they become the standard replacement character.
_SURROGATES = re.compile("[" + chr(0xD800) + "-" + chr(0xDFFF) + "]")

# --------------------------------------------------------------------------- #
# Selective Unicode normalisation
# --------------------------------------------------------------------------- #
# NFKC is great for ligatures, full-width forms and NBSP, but it also rewrites
# characters that carry meaning in technical text (x² -> x2, H₂O -> H2O,
# ½ -> 1⁄2, ℝ -> R). Those characters are protected; everything else is NFKC.
_PRESERVE: frozenset[str] = frozenset(
    {chr(c) for c in range(0x2070, 0x20A0)}  # superscripts & subscripts block
    | {chr(c) for c in range(0x1D2C, 0x1D6C)}  # modifier letters: ᵃ ᵇ ... ᵢ ᵣ ᵤ ᵥ
    | {chr(c) for c in range(0x1D9C, 0x1DC0)}  # more superscript modifier letters
    | {"¹", "²", "³"}  # Latin-1 superscripts
    | {"¼", "½", "¾"}  # Latin-1 vulgar fractions
    | {chr(c) for c in range(0x2150, 0x2160)}  # other vulgar fractions
    | set("ℂℍℕℙℚℝℤ")  # number sets
    | set("ℓℏℵ")  # letter-like math symbols
)


def normalize_unicode(text: str) -> str:
    """NFKC-normalise ``text`` while leaving math-bearing characters untouched."""
    if text.isascii():
        return text
    out: list[str] = []
    pending: list[str] = []
    for char in text:
        if char in _PRESERVE:
            if pending:
                out.append(unicodedata.normalize("NFKC", "".join(pending)))
                pending.clear()
            out.append(char)
        else:
            pending.append(char)
    if pending:
        out.append(unicodedata.normalize("NFKC", "".join(pending)))
    return "".join(out)


# --------------------------------------------------------------------------- #
# Hyphenation repair
# --------------------------------------------------------------------------- #
# A line ending in "-" is either a soft wrap inside one word ("inter-\nnational")
# or a real hyphen ("well-\nknown"). Without a dictionary the safe default is to
# keep the hyphen unless the evidence clearly says "soft wrap": dropping a real
# hyphen ("wellknown") destroys a term, keeping a spurious one ("inter-national")
# is harmless for retrieval.
_HYPHEN_BREAK = re.compile(r"(\S*)-\n(\S+)")

# Prefixes that stay hyphenated in compounds (self-, non-, well-, ...).
_COMPOUND_PREFIXES: frozenset[str] = frozenset(
    {
        "self", "non", "well", "ill", "ex", "all", "half", "high", "low", "long",
        "short", "cross", "full", "part", "real", "state", "time", "single",
        "multi", "end", "peer", "open", "closed", "first", "second", "third",
        "up", "down", "built", "hard", "soft", "large", "small", "one", "two",
        "three", "four", "five", "six", "ten", "mid", "pre", "post", "anti",
    }
)


def _join_hyphen_break(match: re.Match[str]) -> str:
    left, right = match.group(1), match.group(2)
    if not left:  # a standalone "-" at the end of a line: leave as is
        return match.group(0)

    keep = (
        not left[-1].isalpha()  # "1.5E-\n3", "x-\n2", ")-\n"
        or not right[0].islower()  # "Anglo-\nSaxon", "x-\ny"
        or "-" in left  # "state-of-the-\nart" is already a compound
        or left.lstrip("(\"'[").lower() in _COMPOUND_PREFIXES
    )
    return f"{left}-{right}" if keep else f"{left}{right}"


def _clean_line(line: str, keep_indent: bool) -> str:
    body = _MULTI_SPACE.sub(" ", line).strip()
    if keep_indent and body:
        return " " * (len(line) - len(line.lstrip(" "))) + body
    return body


def clean_text(text: str, *, keep_indent: bool = False) -> str:
    """Normalize extracted text without destroying paragraph/heading structure.

    Args:
        text: raw extracted text.
        keep_indent: keep each line's leading spaces (used for nested list
            items); runs of spaces inside a line are still collapsed.
    """
    if not text:
        return ""
    text = _SURROGATES.sub("\ufffd", text)
    text = normalize_unicode(text)
    for src, dst in _LIGATURES.items():
        text = text.replace(src, dst)
    text = _INVISIBLE.sub("", _CONTROL.sub("", text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_BREAK.sub(_join_hyphen_break, text)  # repair words split across lines
    lines = [_clean_line(ln, keep_indent) for ln in text.split("\n")]
    text = "\n".join(lines)
    return _MULTI_NEWLINE.sub("\n\n", text).strip()


def is_heading(line: str) -> bool:
    """Heuristic heading detector (numbered, ALL CAPS, or short title-like)."""
    s = line.strip()
    if not s or len(s) > 100 or s.endswith((".", ",", ";")):
        return False
    if re.match(r"^(\d+(\.\d+)*\.?|[IVX]+\.|Chapter\s+\d+)\s+\S+", s, re.I):
        return True
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and len(s.split()) <= 10 and (s.isupper() or s.istitle())


def mark_headings(text: str) -> str:
    """Prefix detected headings with ``## `` so downstream chunkers can split on them."""
    out: list[str] = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        prev_blank = i == 0 or not lines[i - 1].strip()
        next_blank = i == len(lines) - 1 or not lines[i + 1].strip()
        if prev_blank and next_blank and is_heading(line):
            out.append(f"## {line.strip()}")
        else:
            out.append(line)
    return "\n".join(out)


def cell_clean(cell: object) -> str:
    """Normalize a single table cell."""
    if cell is None:
        return ""
    # same Unicode repair as body text (ligatures, zero-width, surrogates), one line per cell
    return clean_text(str(cell).replace("\n", " "))

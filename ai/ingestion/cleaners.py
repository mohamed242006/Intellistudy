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


# --------------------------------------------------------------------------- #
# Symbol-font private-use glyphs
# --------------------------------------------------------------------------- #
# Office and PDF producers store Symbol-font text at U+F0xx (code point = Symbol
# byte) and the big-bracket pieces of the Adobe Symbol set at U+F8xx. They show
# up as unreadable boxes once the font is gone ("M/M/c/<box>/N" = M/M/c/infinity/N).
# Only unambiguous Symbol codes are mapped; codes that Wingdings also uses as
# bullets (U+F0A7-F0AA, F0D8, F0FC, F076) are left alone.
_SYMBOL_GREEK_UPPER = (
    0x0391, 0x0392, 0x03A7, 0x0394, 0x0395, 0x03A6, 0x0393, 0x0397, 0x0399, 0x03D1, 0x039A, 0x039B, 0x039C,
    0x039D, 0x039F, 0x03A0, 0x0398, 0x03A1, 0x03A3, 0x03A4, 0x03A5, 0x03C2, 0x03A9, 0x039E, 0x03A8, 0x0396,
)
_SYMBOL_GREEK_LOWER = (
    0x03B1, 0x03B2, 0x03C7, 0x03B4, 0x03B5, 0x03C6, 0x03B3, 0x03B7, 0x03B9, 0x03D5, 0x03BA, 0x03BB, 0x03BC,
    0x03BD, 0x03BF, 0x03C0, 0x03B8, 0x03C1, 0x03C3, 0x03C4, 0x03C5, 0x03D6, 0x03C9, 0x03BE, 0x03C8, 0x03B6,
)
_SYMBOL_HIGH = {
    0xA1: 0x03D2, 0xA2: 0x2032, 0xA3: 0x2264, 0xA4: 0x2044, 0xA5: 0x221E, 0xA6: 0x0192, 0xAB: 0x2194,
    0xAC: 0x2190, 0xAD: 0x2191, 0xAE: 0x2192, 0xAF: 0x2193, 0xB0: 0x00B0, 0xB1: 0x00B1, 0xB2: 0x2033,
    0xB3: 0x2265, 0xB4: 0x00D7, 0xB5: 0x221D, 0xB6: 0x2202, 0xB7: 0x2022, 0xB8: 0x00F7, 0xB9: 0x2260,
    0xBA: 0x2261, 0xBB: 0x2248, 0xBC: 0x2026, 0xBD: 0x23D0, 0xBE: 0x23AF, 0xBF: 0x21B5, 0xC0: 0x2135,
    0xC1: 0x2111, 0xC2: 0x211C, 0xC3: 0x2118, 0xC4: 0x2297, 0xC5: 0x2295, 0xC6: 0x2205, 0xC7: 0x2229,
    0xC8: 0x222A, 0xC9: 0x2283, 0xCA: 0x2287, 0xCB: 0x2284, 0xCC: 0x2282, 0xCD: 0x2286, 0xCE: 0x2208,
    0xCF: 0x2209, 0xD0: 0x2220, 0xD1: 0x2207, 0xD2: 0x00AE, 0xD3: 0x00A9, 0xD4: 0x2122, 0xD5: 0x220F,
    0xD6: 0x221A, 0xD7: 0x22C5, 0xD9: 0x2227, 0xDA: 0x2228, 0xDB: 0x21D4, 0xDC: 0x21D0, 0xDD: 0x21D1,
    0xDE: 0x21D2, 0xDF: 0x21D3, 0xE0: 0x25CA, 0xE5: 0x2211, 0xF2: 0x222B, 0xF3: 0x2320, 0xF5: 0x2321,
}
_SYMBOL_PIECES = {  # Adobe Symbol bracket/brace pieces at U+F8xx
    0xF8E5: 0x23AF, 0xF8E6: 0x23D0, 0xF8E7: 0x23AF, 0xF8E8: 0x00AE, 0xF8E9: 0x00A9, 0xF8EA: 0x2122,
    0xF8EB: 0x239B, 0xF8EC: 0x239C, 0xF8ED: 0x239D, 0xF8EE: 0x23A1, 0xF8EF: 0x23A2, 0xF8F0: 0x23A3,
    0xF8F1: 0x23A7, 0xF8F2: 0x23A8, 0xF8F3: 0x23A9, 0xF8F4: 0x23AA, 0xF8F5: 0x23AE, 0xF8F6: 0x239E,
    0xF8F7: 0x239F, 0xF8F8: 0x23A0, 0xF8F9: 0x23A4, 0xF8FA: 0x23A5, 0xF8FB: 0x23A6, 0xF8FC: 0x23AB,
    0xF8FD: 0x23AC, 0xF8FE: 0x23AD,
}
_SYMBOL_ASCII_EXCEPTIONS = {0x2A: 0x2217, 0x2D: 0x2212, 0x27: 0x220B, 0x40: 0x2245, 0x5C: 0x2234, 0x5E: 0x22A5, 0x7E: 0x223C}


def _build_symbol_map() -> dict[int, int]:
    table: dict[int, int] = {0xF000 + code: code for code in range(0x20, 0x7F) if code != 0x76}
    table.update({0xF000 + code: target for code, target in _SYMBOL_ASCII_EXCEPTIONS.items()})
    table.update({0xF000 + 0x41 + i: cp for i, cp in enumerate(_SYMBOL_GREEK_UPPER)})
    table.update({0xF000 + 0x61 + i: cp for i, cp in enumerate(_SYMBOL_GREEK_LOWER) if 0x61 + i != 0x76})
    table.update({0xF000 + code: cp for code, cp in _SYMBOL_HIGH.items()})
    table.update(_SYMBOL_PIECES)
    return table


_SYMBOL_PUA = _build_symbol_map()



def normalize_unicode(text: str) -> str:
    """NFKC-normalise ``text`` while leaving math-bearing characters untouched."""
    if text.isascii():
        return text
    text = text.translate(_SYMBOL_PUA)
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

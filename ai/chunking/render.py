"""Single place that decides how tables are turned into text for chunks.

The ingestion readers differ (PDF: pipe text, DOCX/PPTX: key/value); chunking
re-renders from ``TableData.rows`` so every format looks the same downstream.
"""

from __future__ import annotations

Rows = list[list[str]]


def _cell(value: str) -> str:
    return " ".join(str(value).replace("|", "/").split())


def to_markdown(rows: Rows) -> str:
    """Markdown pipe table; the first row is the header when there is more than one row."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    padded = [[_cell(c) for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(padded[0]) + " |"]
    if len(padded) > 1:
        lines.append("| " + " | ".join(["---"] * width) + " |")
        lines.extend("| " + " | ".join(r) + " |" for r in padded[1:])
    return "\n".join(lines)


def to_key_value(rows: Rows) -> str:
    """``Header: value`` lines per data row, rows separated by a blank line (embedding form)."""
    if not rows:
        return ""
    if len(rows) == 1:
        return " | ".join(_cell(c) for c in rows[0] if c)
    header = [_cell(c) for c in rows[0]]
    blocks: list[str] = []
    for row in rows[1:]:
        lines = []
        for i, cell in enumerate(row):
            value = _cell(cell)
            if not value:
                continue
            label = header[i] if i < len(header) and header[i] else f"Column {i + 1}"
            lines.append(f"{label}: {value}")
        if lines:
            blocks.append("\n".join(lines))
    return "\n\n".join(blocks)

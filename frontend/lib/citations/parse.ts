/**
 * Citation markers in summary and answer text (gate GF1-07). The backend writes `[n]` or `[n, m, …]` after a statement
 * (backend/app/services/summaries.py, ai/answering/citations.py render). Only that syntax is recognised, and only
 * numbers present in the SAME owner's citations become badges; everything else stays literal text, exactly as sent.
 * Nothing is renumbered, merged, inferred or interpreted as markup.
 */

export type CitationSegment = { kind: "text"; text: string } | { kind: "cite"; number: number };

const MARKER = /\[(\d{1,4}(?:, ?\d{1,4})*)\]/g;

export function parseCitations(text: string, known: ReadonlySet<number>): CitationSegment[] {
  const out: CitationSegment[] = [];
  const pushText = (value: string) => {
    if (!value) return;
    const last = out[out.length - 1];
    if (last?.kind === "text") last.text += value;
    else out.push({ kind: "text", text: value });
  };
  let cursor = 0;
  for (const match of text.matchAll(MARKER)) {
    const start = match.index ?? 0;
    pushText(text.slice(cursor, start));
    const numbers = match[1]!.split(",").map((part) => Number(part.trim()));
    if (numbers.every((n) => known.has(n))) {
      for (const number of numbers) out.push({ kind: "cite", number });
    } else {
      pushText(match[0]); // an unknown number keeps the whole marker visible as text, never a guessed source
    }
    cursor = start + match[0].length;
  }
  pushText(text.slice(cursor));
  return out;
}

/** Split summary text into statements: only after a citation marker followed by sentence punctuation and a space. */
export function splitStatements(text: string): string[] {
  const parts = text.split(/(?<=\[\d{1,4}(?:, ?\d{1,4})*\][.!?])\s+/);
  return parts.map((part) => part.trim()).filter(Boolean);
}

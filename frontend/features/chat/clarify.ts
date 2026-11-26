/**
 * Guidance after a "not found" answer (never a different answer): the backend's refusal stays as it is; these helpers
 * only suggest a better question built from real data (the course's ready files and the backend's closest material).
 * Nothing here is sent automatically: a suggestion fills the composer and the reader decides.
 */

/** A question that points at a place ("the first paragraph", "this slide") without naming a file or a page number. */
const PLACE = /\b(?:first|second|third|last|next|previous|this|that|the|above|below)\s+(?:paragraph|page|slide|section|chapter|part|lecture|file|document|table|figure|example|line)s?\b/i;
const NAMES_PAGE = /\b(?:page|slide|p\.)\s*\d+\b/i;

export function isVagueReference(question: string, fileNames: readonly string[]): boolean {
  if (!PLACE.test(question) || NAMES_PAGE.test(question)) return false;
  const lower = question.toLowerCase();
  return !fileNames.some((name) => {
    const stem = name.replace(/\.[a-z0-9]+$/i, "").toLowerCase();
    return stem.length >= 3 && lower.includes(stem);
  });
}

/** The reader's question, pointed at one file; the page stays theirs to add. */
export function scopedQuestion(question: string, fileName: string): string {
  return `In “${fileName}”: ${question.trim()}`;
}

/** Follow-ups from the backend's closest material: "Explain page 3 of “a.pdf”." (distinct, at most `max`). */
export function followUps(nearest: ReadonlyArray<{ file_name: string; citation_label: string }>, max = 2): string[] {
  const out: string[] = [];
  for (const source of nearest) {
    const text = `Explain ${source.citation_label.charAt(0).toLowerCase()}${source.citation_label.slice(1)} of “${source.file_name}”.`;
    if (!out.includes(text)) out.push(text);
    if (out.length >= max) break;
  }
  return out;
}

/** Starter questions for an empty conversation, one per ready file (at most `max`). */
export function starterQuestions(fileNames: readonly string[], max = 3): string[] {
  return fileNames.slice(0, max).map((name) => `Summarise the key ideas in “${name}”.`);
}

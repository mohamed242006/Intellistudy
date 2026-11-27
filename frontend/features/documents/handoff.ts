/**
 * Hands the workspace's checked files to the Quiz page or the chat ("Create quiz", "Ask selected materials") without
 * putting up to 20 ids in the URL. In-memory application state only (web storage is never used, GF0A-07): it survives
 * client-side navigation (router.push), not a reload. Per course and target, trusted for 10 minutes; the receiving page
 * still drops anything that is not a ready file of the course. Reading leaves the value for repeated reads in the same
 * page load (React StrictMode); a newer hand-off replaces it.
 */
const TTL_MS = 10 * 60 * 1000;

export type HandoffTarget = "quiz" | "chat";

const store = new Map<string, { ids: string[]; at: number }>();

export function handOff(courseId: string, target: HandoffTarget, ids: readonly string[]): void {
  store.set(`${target}:${courseId}`, { ids: [...new Set(ids)].slice(0, 20), at: Date.now() });
}

export function takeHandoff(courseId: string, target: HandoffTarget): string[] {
  const entry = store.get(`${target}:${courseId}`);
  if (!entry || Date.now() - entry.at > TTL_MS) return [];
  return [...entry.ids];
}

/** Forget every hand-off (sign-out clears application state). */
export function clearHandoffs(): void {
  store.clear();
}

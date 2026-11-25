/**
 * Processing-status polling rules (gate GF0B-19; UI §18 D-19). Pure, so they are unit-tested directly.
 * - Poll only while at least one listed document is in progress.
 * - About 2 s; after failed polls the delay doubles up to 30 s; after MAX_POLL_FAILURES failed polls in a row it
 *   stops and the UI offers "Try again".
 * - While the tab is hidden TanStack Query does not run interval fetches (refetchIntervalInBackground is false).
 */
import type { DocumentOut } from "@/lib/api/types";
import { isInProgress } from "./status";

export const POLL_INTERVAL_MS = 2_000;
export const MAX_POLL_DELAY_MS = 30_000;
export const MAX_POLL_FAILURES = 5;

export function pollDelay(docs: readonly Pick<DocumentOut, "status">[], consecutiveFailures: number): number | false {
  if (consecutiveFailures >= MAX_POLL_FAILURES) return false;
  if (!docs.some((doc) => isInProgress(doc.status))) return false;
  return Math.min(POLL_INTERVAL_MS * 2 ** consecutiveFailures, MAX_POLL_DELAY_MS);
}

/** Counts failed fetches since the last successful one from a query's state counters (no extra render state). */
export type FailureTracker = { dataUpdatedAt: number; errorsAtSuccess: number };

export function newFailureTracker(): FailureTracker {
  return { dataUpdatedAt: 0, errorsAtSuccess: 0 };
}

export function consecutiveFailures(tracker: FailureTracker, state: { dataUpdatedAt: number; errorUpdateCount: number }): number {
  if (state.dataUpdatedAt !== tracker.dataUpdatedAt) {
    tracker.dataUpdatedAt = state.dataUpdatedAt;
    tracker.errorsAtSuccess = state.errorUpdateCount;
  }
  return Math.max(0, state.errorUpdateCount - tracker.errorsAtSuccess);
}

import { ApiError } from "@/lib/api/errors";
import { PROVISIONAL } from "./strings";

/** Safe sentence for a failed document action (retry, delete, download); never the raw problem body (GF0B-26). */
export function documentActionError(error: unknown): string {
  if (!(error instanceof ApiError)) return PROVISIONAL.actionFailed;
  if (error.code === "not_failed") return PROVISIONAL.retryConflict;
  if (error.code === "queue_full") return PROVISIONAL.queueFull;
  if (error.kind === "not_found") return PROVISIONAL.notFound;
  if (error.kind === "network") return PROVISIONAL.networkFailed;
  if (error.kind === "session_expired") return PROVISIONAL.sessionExpired;
  if (error.code === "rate_limited") return PROVISIONAL.rateLimited(error.retryAfterSeconds === null ? PROVISIONAL.inAWhile : PROVISIONAL.inSeconds(error.retryAfterSeconds));
  return PROVISIONAL.actionFailed;
}

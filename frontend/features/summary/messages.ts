import { ApiError } from "@/lib/api/errors";
import { waitPhrase } from "@/lib/hooks/use-retry-after";
import { FAILURE, LOAD_PROBLEM } from "./strings";

/** Fixed copy for a summary request failure; never the problem body (GF1-05). */
export function summaryRequestError(error: unknown): string {
  if (!(error instanceof ApiError)) return FAILURE.fallback!;
  if (error.code === "token_budget") return FAILURE.token_budget!;
  if (error.code === "rate_limited") return `${FAILURE.rate_limited} Try again ${error.retryAfterSeconds === null ? "later" : waitPhrase(error.retryAfterSeconds)}.`;
  if (error.code && FAILURE[error.code]) return FAILURE[error.code]!;
  if (error.kind === "server") return FAILURE.server!;
  if (error.kind === "network" || error.kind === "session_expired" || error.kind === "not_found") return FAILURE[error.kind]!;
  return FAILURE.fallback!;
}

/** Fixed copy for a failed generation (`error_code` of SummaryOut). */
export function generationFailure(code: string | null): string {
  return (code && FAILURE[code]) || FAILURE.internal_error!;
}

/**
 * A failed summary LOAD, classified from the real response: no connection, a database behind the code (503
 * database_outdated), another server error, an expired session. A missing summary is not an error (GET 404 → null).
 */
export function summaryLoadProblem(error: unknown): { title: string; body: string } {
  if (!(error instanceof ApiError)) return LOAD_PROBLEM.other;
  if (error.kind === "network") return LOAD_PROBLEM.network;
  if (error.code === "database_outdated") return LOAD_PROBLEM.database_outdated;
  if (error.kind === "server") return LOAD_PROBLEM.server;
  if (error.kind === "session_expired" || error.kind === "unauthorized") return LOAD_PROBLEM.session;
  return LOAD_PROBLEM.other;
}

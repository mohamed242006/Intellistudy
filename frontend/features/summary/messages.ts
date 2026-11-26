import { ApiError } from "@/lib/api/errors";
import { waitPhrase } from "@/lib/hooks/use-retry-after";
import { FAILURE } from "./strings";

/** Fixed copy for a summary request failure; never the problem body (GF1-05). */
export function summaryRequestError(error: unknown): string {
  if (!(error instanceof ApiError)) return FAILURE.fallback!;
  if (error.code === "token_budget") return FAILURE.token_budget!;
  if (error.code === "rate_limited") return `${FAILURE.rate_limited} Try again ${error.retryAfterSeconds === null ? "later" : waitPhrase(error.retryAfterSeconds)}.`;
  if (error.code && FAILURE[error.code]) return FAILURE[error.code]!;
  if (error.kind === "network" || error.kind === "session_expired" || error.kind === "not_found") return FAILURE[error.kind]!;
  return FAILURE.fallback!;
}

/** Fixed copy for a failed generation (`error_code` of SummaryOut). */
export function generationFailure(code: string | null): string {
  return (code && FAILURE[code]) || FAILURE.internal_error!;
}

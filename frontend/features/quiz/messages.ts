import { ApiError } from "@/lib/api/errors";
import { waitPhrase } from "@/lib/hooks/use-retry-after";
import { ERRORS } from "./strings";

/** Fixed copy for a quiz or attempt failure; never the problem body (GF2-19). */
export function quizError(error: unknown): string {
  if (!(error instanceof ApiError)) return ERRORS.fallback!;
  if (error.code === "rate_limited") return `Too many requests. Try again ${error.retryAfterSeconds === null ? "later" : waitPhrase(error.retryAfterSeconds)}.`;
  if (error.code && ERRORS[error.code]) return ERRORS[error.code]!;
  if (ERRORS[error.kind]) return ERRORS[error.kind]!;
  return ERRORS.fallback!;
}

/** Reason a generation failed (`error_code` of QuizOut). */
export function generationFailure(code: string | null): string {
  return (code && ERRORS[code]) || ERRORS.internal_error!;
}

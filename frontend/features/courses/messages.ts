import { ApiError } from "@/lib/api/errors";
import { COURSE_ERRORS } from "./strings";

/** Form-level message for any other failure; never the raw problem body (GF0B-26). */
export function courseFormError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.kind === "network") return COURSE_ERRORS.offline;
    if (error.kind === "not_found") return COURSE_ERRORS.gone;
    if (error.kind === "rate_limited") return COURSE_ERRORS.rateLimited;
  }
  return COURSE_ERRORS.saveFailed;
}

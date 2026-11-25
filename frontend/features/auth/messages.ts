/** Turns an error into the one message the UI may show (gate GF0A-13). Never shows internals. */

import { ApiError } from "@/lib/api/errors";
import { BACKEND, PROVISIONAL } from "./strings";

export type FormFailure = { field: "email" | "name" | "password" | null; message: string };

export function messageFor(error: unknown): FormFailure {
  if (!(error instanceof ApiError)) return { field: null, message: PROVISIONAL.unexpected };
  switch (error.kind) {
    case "invalid_credentials":
      return { field: null, message: BACKEND.invalidCredentials };
    case "registration_rejected":
      return { field: null, message: BACKEND.registrationRejected };
    case "validation":
      return error.field && error.userMessage
        ? { field: error.field, message: error.userMessage }
        : { field: null, message: PROVISIONAL.checkFields };
    case "rate_limited":
      return {
        field: null,
        message: error.retryAfterSeconds ? PROVISIONAL.rateLimitedSeconds(error.retryAfterSeconds) : PROVISIONAL.rateLimited,
      };
    case "network":
      return { field: null, message: PROVISIONAL.network };
    case "session_expired":
    case "unauthorized":
      return { field: null, message: BACKEND.sessionExpired };
    default:
      return { field: null, message: PROVISIONAL.unexpected };
  }
}

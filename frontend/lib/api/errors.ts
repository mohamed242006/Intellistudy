/**
 * Typed errors from the backend's RFC 7807 problem documents (backend/app/core/errors.py): `type` is
 * `about:blank#<code>`; `detail` is client-safe but is shown only for codes whose text the UI is meant to show.
 * Nothing else from a response (stack traces, internals) is ever surfaced.
 */

export type ApiErrorKind =
  | "validation" // 422 validation_error, invalid_email, invalid_name, weak_password
  | "invalid_credentials" // 401 on login: unknown email, wrong password, locked or disabled account (one message)
  | "registration_rejected" // 409: generic, does not reveal whether the email exists
  | "unauthorized" // 401 on a protected request
  | "session_expired" // refresh failed or the retried request was refused again
  | "forbidden" // 403 (for example csrf_rejected)
  | "rate_limited" // 429, with Retry-After when the backend sent it
  | "not_found"
  | "network" // no response at all
  | "server" // 5xx
  | "unknown";

/** Field that a backend validation code belongs to (register: backend/app/services/auth.py). */
const FIELD_OF_CODE: Record<string, "email" | "name" | "password"> = {
  invalid_email: "email",
  invalid_name: "name",
  weak_password: "password",
};

/** Codes whose `detail` is a fixed, client-safe sentence written by the backend for the user. */
const SHOWABLE_DETAIL = new Set(["invalid_email", "invalid_name", "weak_password"]);

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly code: string;
  readonly field: "email" | "name" | "password" | null;
  readonly userMessage: string | null; // backend sentence safe to show, or null (the UI uses its own copy)
  readonly retryAfterSeconds: number | null;

  constructor(init: {
    kind: ApiErrorKind;
    status: number;
    code?: string;
    field?: "email" | "name" | "password" | null;
    userMessage?: string | null;
    retryAfterSeconds?: number | null;
  }) {
    super(init.code || init.kind);
    this.name = "ApiError";
    this.kind = init.kind;
    this.status = init.status;
    this.code = init.code ?? "";
    this.field = init.field ?? null;
    this.userMessage = init.userMessage ?? null;
    this.retryAfterSeconds = init.retryAfterSeconds ?? null;
  }
}

function codeOf(type: unknown): string {
  return typeof type === "string" && type.startsWith("about:blank#") ? type.slice("about:blank#".length) : "";
}

function retryAfter(headers: Headers): number | null {
  const raw = headers.get("retry-after");
  if (raw === null || !/^\d{1,6}$/.test(raw.trim())) return null;
  return Number(raw.trim());
}

/** Build an ApiError from a non-2xx response without trusting its body. */
export async function apiErrorFrom(response: Response, context: { login?: boolean } = {}): Promise<ApiError> {
  let body: Record<string, unknown> = {};
  try {
    const parsed: unknown = await response.json();
    if (parsed && typeof parsed === "object") body = parsed as Record<string, unknown>;
  } catch {
    // not JSON: fall back on the status alone
  }
  const status = response.status;
  const code = codeOf(body.type);
  const detail = typeof body.detail === "string" && SHOWABLE_DETAIL.has(code) ? body.detail : null;
  const base = { status, code, retryAfterSeconds: retryAfter(response.headers) };

  if (status === 429) return new ApiError({ ...base, kind: "rate_limited" });
  if (status === 401) return new ApiError({ ...base, kind: context.login ? "invalid_credentials" : "unauthorized" });
  if (status === 409 && code === "registration_rejected") return new ApiError({ ...base, kind: "registration_rejected" });
  if (status === 422) {
    return new ApiError({ ...base, kind: "validation", field: FIELD_OF_CODE[code] ?? null, userMessage: detail });
  }
  if (status === 403) return new ApiError({ ...base, kind: "forbidden" });
  if (status === 404) return new ApiError({ ...base, kind: "not_found" });
  if (status >= 500) return new ApiError({ ...base, kind: "server" });
  return new ApiError({ ...base, kind: "unknown" });
}

export function networkError(): ApiError {
  return new ApiError({ kind: "network", status: 0 });
}

export function sessionExpiredError(): ApiError {
  return new ApiError({ kind: "session_expired", status: 401 });
}

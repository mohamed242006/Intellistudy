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
  | "conflict" // 409 other than registration_rejected (for example not_failed)
  | "too_large" // 413 file_too_large, quota_exceeded
  | "unsupported_media" // 415
  | "bad_request" // 400 (for example malformed_upload)
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

/** One rejected file of a 422 `upload_rejected` problem (backend/app/services/documents.py, contract UPL-13). */
export type FileProblem = { file: string; reason: string };

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number;
  readonly code: string;
  readonly field: "email" | "name" | "password" | null;
  readonly userMessage: string | null; // backend sentence safe to show, or null (the UI uses its own copy)
  readonly retryAfterSeconds: number | null;
  /** Per-file reasons of an `upload_rejected` problem (reason codes only; the UI writes its own sentences). */
  readonly files: readonly FileProblem[];

  constructor(init: {
    kind: ApiErrorKind;
    status: number;
    code?: string;
    field?: "email" | "name" | "password" | null;
    userMessage?: string | null;
    retryAfterSeconds?: number | null;
    files?: readonly FileProblem[];
  }) {
    super(init.code || init.kind);
    this.name = "ApiError";
    this.kind = init.kind;
    this.status = init.status;
    this.code = init.code ?? "";
    this.field = init.field ?? null;
    this.userMessage = init.userMessage ?? null;
    this.retryAfterSeconds = init.retryAfterSeconds ?? null;
    this.files = init.files ?? [];
  }
}

function codeOf(type: unknown): string {
  return typeof type === "string" && type.startsWith("about:blank#") ? type.slice("about:blank#".length) : "";
}

function retryAfter(raw: string | null): number | null {
  if (raw === null || !/^\d{1,6}$/.test(raw.trim())) return null;
  return Number(raw.trim());
}

const REASON_CODE = /^[a-z_]{1,40}$/;

/** Only well-formed reason codes and bounded names are kept from `files`; anything else in the body is ignored. */
function fileProblems(raw: unknown): FileProblem[] {
  if (!Array.isArray(raw)) return [];
  return raw.slice(0, 10).flatMap((item: unknown) => {
    if (!item || typeof item !== "object") return [];
    const { file, reason } = item as Record<string, unknown>;
    if (typeof reason !== "string" || !REASON_CODE.test(reason)) return [];
    return [{ file: typeof file === "string" ? file.slice(0, 255) : "", reason }];
  });
}

/** Build an ApiError from a status, a parsed problem body and the Retry-After header, without trusting the body. */
export function apiErrorFromBody(
  status: number,
  parsed: unknown,
  retryAfterHeader: string | null,
  context: { login?: boolean } = {},
): ApiError {
  const body: Record<string, unknown> = parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : {};
  const code = codeOf(body.type);
  const detail = typeof body.detail === "string" && SHOWABLE_DETAIL.has(code) ? body.detail : null;
  const base = { status, code, retryAfterSeconds: retryAfter(retryAfterHeader) };

  if (status === 429) return new ApiError({ ...base, kind: "rate_limited" });
  if (status === 401) return new ApiError({ ...base, kind: context.login ? "invalid_credentials" : "unauthorized" });
  if (status === 409 && code === "registration_rejected") return new ApiError({ ...base, kind: "registration_rejected" });
  if (status === 409) return new ApiError({ ...base, kind: "conflict" });
  if (status === 422) {
    return new ApiError({
      ...base,
      kind: "validation",
      field: FIELD_OF_CODE[code] ?? null,
      userMessage: detail,
      files: code === "upload_rejected" ? fileProblems(body.files) : [],
    });
  }
  if (status === 413) return new ApiError({ ...base, kind: "too_large" });
  if (status === 415) return new ApiError({ ...base, kind: "unsupported_media" });
  if (status === 400) return new ApiError({ ...base, kind: "bad_request" });
  if (status === 403) return new ApiError({ ...base, kind: "forbidden" });
  if (status === 404) return new ApiError({ ...base, kind: "not_found" });
  if (status >= 500) return new ApiError({ ...base, kind: "server" });
  return new ApiError({ ...base, kind: "unknown" });
}

/** Build an ApiError from a non-2xx response without trusting its body. */
export async function apiErrorFrom(response: Response, context: { login?: boolean } = {}): Promise<ApiError> {
  let parsed: unknown = null;
  try {
    parsed = await response.json();
  } catch {
    // not JSON: fall back on the status alone
  }
  return apiErrorFromBody(response.status, parsed, response.headers.get("retry-after"), context);
}

export function networkError(): ApiError {
  return new ApiError({ kind: "network", status: 0 });
}

export function sessionExpiredError(): ApiError {
  return new ApiError({ kind: "session_expired", status: 401 });
}

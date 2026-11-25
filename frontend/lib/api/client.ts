/**
 * The only way frontend code talks to the backend (/api/v1, same origin through the Next.js rewrite).
 *
 * - `Authorization: Bearer` is added only when an access token is in memory and the call is authenticated (GF0A-08).
 * - Cookies are sent only to the auth endpoints that need them (login sets, refresh and logout read the refresh
 *   cookie); every other call uses `credentials: "omit"`.
 * - A protected call answered 401 triggers one coordinated refresh and one retry; a second failure ends the session
 *   (GF0A-09). Nothing about the request or the token is logged.
 */

import { refreshSession } from "@/lib/auth/refresh";
import { tokenStore } from "@/lib/auth/token-store";
import { ApiError, apiErrorFrom, networkError, sessionExpiredError } from "./errors";

export const API_BASE = "/api/v1";

export type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  /** Send the bearer token and apply the refresh-and-retry rule (default true). */
  auth?: boolean;
  /** Send and accept cookies (auth endpoints only). */
  cookies?: boolean;
  /** Add the CSRF header required by cookie-authenticated endpoints. */
  csrf?: boolean;
  /** The 401 of this endpoint means wrong credentials, not an expired session (login). */
  login?: boolean;
  signal?: AbortSignal;
};

type SessionListener = () => void;
const expiryListeners = new Set<SessionListener>();

/** Notified when the session ends because refresh failed (the UI navigates to /signin). */
export function onSessionExpired(listener: SessionListener): () => void {
  expiryListeners.add(listener);
  return () => expiryListeners.delete(listener);
}

function endSession(): void {
  tokenStore.clear();
  for (const listener of expiryListeners) listener();
}

/** Ends the session after a failed refresh; used by transports that do not go through apiRequest (upload.ts). */
export function expireSession(): void {
  endSession();
}

async function send(path: string, options: RequestOptions, accept = "application/json"): Promise<Response> {
  const headers: Record<string, string> = { Accept: accept };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const token = options.auth === false ? null : tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.csrf) headers["X-Requested-With"] = "IntelliStudy";
  try {
    return await fetch(`${API_BASE}${path}`, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      credentials: options.cookies ? "same-origin" : "omit",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw networkError();
  }
}

async function parse<T>(response: Response): Promise<T> {
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const authenticated = options.auth !== false;
  const response = await send(path, options);
  if (response.ok) return parse<T>(response);
  if (response.status !== 401 || !authenticated) throw await apiErrorFrom(response, { login: options.login });

  // One coordinated refresh, then one retry (GF0A-09, GF0A-10).
  const refreshed = await refreshSession();
  if (!refreshed) {
    endSession();
    throw sessionExpiredError();
  }
  const retried = await send(path, options);
  if (retried.ok) return parse<T>(retried);
  if (retried.status === 401) {
    endSession();
    throw sessionExpiredError();
  }
  throw await apiErrorFrom(retried);
}

/** Run a protected request with the one-refresh-one-retry rule and return the raw successful Response. */
async function sendWithRefresh(path: string, options: RequestOptions, accept: string): Promise<Response> {
  const response = await send(path, options, accept);
  if (response.ok) return response;
  if (response.status !== 401) throw await apiErrorFrom(response);
  const refreshed = await refreshSession();
  if (!refreshed) {
    endSession();
    throw sessionExpiredError();
  }
  const retried = await send(path, options, accept);
  if (retried.ok) return retried;
  if (retried.status === 401) {
    endSession();
    throw sessionExpiredError();
  }
  throw await apiErrorFrom(retried);
}

/**
 * The file name of an `attachment` Content-Disposition (RFC 6266 `filename*=UTF-8''…`, as the backend sends it), or
 * null. The name is used only as the `download` attribute of a programmatic anchor, never as markup or a path.
 */
export function attachmentFileName(header: string | null): string | null {
  if (!header || !/^\s*attachment\b/i.test(header)) return null;
  const match = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header);
  if (!match?.[1]) return null;
  try {
    const name = decodeURIComponent(match[1].trim());
    return name.replace(/[\\/]/g, "_").slice(0, 255) || null;
  } catch {
    return null;
  }
}

/** Download a protected file as a Blob (GF0B-22). Only `attachment` responses are accepted. */
export async function apiDownload(path: string, signal?: AbortSignal): Promise<{ blob: Blob; fileName: string | null }> {
  const response = await sendWithRefresh(path, { signal }, "*/*");
  const disposition = response.headers.get("content-disposition");
  if (!disposition || !/^\s*attachment\b/i.test(disposition)) throw new ApiError({ kind: "unknown", status: response.status });
  return { blob: await response.blob(), fileName: attachmentFileName(disposition) };
}

/** Query string from defined values only (numbers and booleans); ids never travel in query strings. */
export function query(params: Record<string, number | boolean | undefined>): string {
  const entries = Object.entries(params).filter((entry): entry is [string, number | boolean] => entry[1] !== undefined);
  return entries.length ? `?${entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&")}` : "";
}

export { ApiError };

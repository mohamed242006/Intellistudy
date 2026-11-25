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

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: "application/json" };
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

export { ApiError };

/**
 * Session refresh through the HttpOnly refresh cookie (backend/app/api/v1/auth.py: POST /auth/refresh requires the
 * header X-Requested-With: IntelliStudy and, if sent, an allowed Origin; contract RT-07).
 *
 * Single flight: concurrent callers in this tab share one request (gate GF0A-10); across tabs the request runs under
 * a Web Lock (GF0A-11).
 */

import { TokenResponse } from "@/lib/api/types";
import { withRefreshLock } from "./coordination";
import { tokenStore } from "./token-store";

export const CSRF_HEADER = "X-Requested-With";
export const CSRF_VALUE = "IntelliStudy";

let inflight: Promise<boolean> | null = null;

async function requestRefresh(): Promise<boolean> {
  let response: Response;
  try {
    response = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      headers: { Accept: "application/json", [CSRF_HEADER]: CSRF_VALUE },
      credentials: "same-origin", // the refresh cookie is the credential; Path=/api/v1/auth keeps it off other routes
    });
  } catch {
    return false; // offline: no session can be restored now
  }
  if (!response.ok) {
    tokenStore.clear();
    return false;
  }
  const body = (await response.json()) as TokenResponse;
  tokenStore.set(body.access_token, body.expires_in);
  return true;
}

/** Restore or extend the session. Resolves true when a fresh access token is in memory. */
export function refreshSession(): Promise<boolean> {
  if (!inflight) {
    inflight = withRefreshLock(requestRefresh).finally(() => {
      inflight = null;
    });
  }
  return inflight;
}

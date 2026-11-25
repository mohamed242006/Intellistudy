/** Auth API calls (backend/app/api/v1/auth.py). Passwords are passed through, never stored. */

import { apiRequest } from "@/lib/api/client";
import type { TokenResponse, UserOut } from "@/lib/api/types";
import { broadcastSignOut } from "./coordination";
import { tokenStore } from "./token-store";

export async function login(email: string, password: string): Promise<void> {
  const tokens = await apiRequest<TokenResponse>("/auth/login", {
    method: "POST",
    body: { email, password },
    auth: false,
    cookies: true, // the response sets the refresh cookie
    login: true,
  });
  tokenStore.set(tokens.access_token, tokens.expires_in);
}

/** Registration issues no session (201 UserOut), so the new account signs in with the same credentials. */
export async function register(name: string, email: string, password: string): Promise<void> {
  await apiRequest<UserOut>("/auth/register", { method: "POST", body: { email, name, password }, auth: false });
  await login(email, password);
}

export function fetchMe(): Promise<UserOut> {
  return apiRequest<UserOut>("/auth/me");
}

/** Revoke the refresh token family, then forget everything locally, here and in other tabs (GF0A-12). */
export async function logout(): Promise<void> {
  try {
    await apiRequest<void>("/auth/logout", { method: "POST", auth: false, cookies: true, csrf: true });
  } catch {
    // signing out locally must not depend on the network
  } finally {
    tokenStore.clear();
    broadcastSignOut();
  }
}

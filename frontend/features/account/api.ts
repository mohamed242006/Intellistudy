/** Account calls (backend/app/api/v1/auth.py): change-password and logout-all. Passwords are passed through only. */
import { apiRequest } from "@/lib/api/client";
import type { TokenResponse } from "@/lib/api/types";
import { tokenStore } from "@/lib/auth/token-store";

/**
 * The backend verifies the current password, applies its policy, revokes every session (other devices are signed out)
 * and returns a fresh one for this tab: the new access token replaces the old one; the response sets the refresh cookie.
 */
export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const tokens = await apiRequest<TokenResponse>("/auth/change-password", {
    method: "POST",
    body: { current_password: currentPassword, new_password: newPassword },
    cookies: true,
  });
  tokenStore.set(tokens.access_token, tokens.expires_in);
}

/** Revokes every session of this account, this one included; the caller then signs out locally. */
export async function logoutAll(): Promise<void> {
  await apiRequest<void>("/auth/logout-all", { method: "POST" });
}

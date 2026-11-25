"use client";

/**
 * Session state for the whole app (gate GF0A-14, -16, -17, -12).
 *
 * - Startup: exactly one refresh through the HttpOnly cookie; success loads /auth/me, failure means signed out.
 * - The access token stays in lib/auth/token-store (memory); this context exposes only status and the user profile.
 * - Proactive refresh about two minutes before the 15-minute token expires, while the tab is visible.
 * - Sign-out (here or in another tab) and session expiry clear the token and the TanStack Query cache.
 */

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { onSessionExpired } from "@/lib/api/client";
import type { UserOut } from "@/lib/api/types";
import { onSignOutElsewhere } from "./coordination";
import { refreshSession } from "./refresh";
import { fetchMe, login, logout, register } from "./session";
import { tokenStore } from "./token-store";

export type AuthStatus = "loading" | "authenticated" | "anonymous";

type AuthContextValue = {
  status: AuthStatus;
  user: UserOut | null;
  /** Why the last session ended, for the sign-in page ("expired" after a failed refresh). */
  endReason: "expired" | "signed-out" | null;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (name: string, email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const REFRESH_MARGIN_MS = 120_000;

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<UserOut | null>(null);
  const [endReason, setEndReason] = useState<AuthContextValue["endReason"]>(null);
  const started = useRef(false);

  const reset = useCallback(
    (reason: AuthContextValue["endReason"]) => {
      tokenStore.clear();
      queryClient.clear();
      setUser(null);
      setEndReason(reason);
      setStatus("anonymous");
    },
    [queryClient],
  );

  const loadUser = useCallback(async () => {
    const me = await fetchMe();
    setUser(me);
    setEndReason(null);
    setStatus("authenticated");
  }, []);

  // Startup: one refresh (React StrictMode's second effect run is ignored).
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void (async () => {
      const restored = await refreshSession();
      if (!restored) {
        setStatus("anonymous");
        return;
      }
      try {
        await loadUser();
      } catch {
        reset(null);
      }
    })();
  }, [loadUser, reset]);

  useEffect(() => onSessionExpired(() => reset("expired")), [reset]);
  useEffect(() => onSignOutElsewhere(() => reset("signed-out")), [reset]);

  // Proactive refresh before expiry, only while the tab is visible.
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = () => {
      if (timer) clearTimeout(timer);
      const expiresAt = tokenStore.expiresAt();
      if (!expiresAt) return;
      const delay = Math.max(expiresAt - Date.now() - REFRESH_MARGIN_MS, 0);
      timer = setTimeout(() => {
        if (typeof document !== "undefined" && document.visibilityState !== "visible") return;
        void refreshSession().then((ok) => {
          if (!ok) reset("expired");
        });
      }, delay);
    };
    schedule();
    const unsubscribe = tokenStore.subscribe(schedule);
    return () => {
      unsubscribe();
      if (timer) clearTimeout(timer);
    };
  }, [reset]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      await login(email, password);
      await loadUser();
    },
    [loadUser],
  );

  const signUp = useCallback(
    async (name: string, email: string, password: string) => {
      await register(name, email, password);
      await loadUser();
    },
    [loadUser],
  );

  const signOut = useCallback(async () => {
    await logout();
    reset("signed-out");
  }, [reset]);

  const value = useMemo(
    () => ({ status, user, endReason, signIn, signUp, signOut }),
    [status, user, endReason, signIn, signUp, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

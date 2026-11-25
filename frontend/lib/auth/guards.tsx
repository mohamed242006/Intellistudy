"use client";

/** Client-side route protection (gate GF0A-18). The session lives in memory, so the server cannot guard routes. */

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { safeNextPath } from "@/lib/navigation/safe-next";
import { useAuth } from "./auth-provider";

function Pending() {
  return <div aria-busy="true" aria-live="polite" className="min-h-screen bg-canvas" />;
}

/** Protected routes: anonymous visitors go to /signin with a same-origin return path. */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "anonymous") router.replace(`/signin?next=${encodeURIComponent(pathname || "/")}`);
  }, [status, pathname, router]);

  return status === "authenticated" ? <>{children}</> : <Pending />;
}

/** Auth pages: a signed-in user goes to the return path (or the landing route). */
export function RedirectIfAuthenticated({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const next = useSearchParams().get("next");

  useEffect(() => {
    if (status === "authenticated") router.replace(safeNextPath(next));
  }, [status, next, router]);

  return status === "anonymous" ? <>{children}</> : <Pending />;
}

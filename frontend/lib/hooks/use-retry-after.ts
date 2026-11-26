"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api/errors";

/**
 * Holds an action back after a 429 until its `Retry-After` has passed (gates GF1-05, GF1-16). Nothing is retried
 * automatically: the control is only re-enabled. Returns whether the action is blocked and the wait in seconds.
 */
export function useRetryAfter(now: () => number = Date.now) {
  const [until, setUntil] = useState(0);
  const [, tick] = useState(0);

  useEffect(() => {
    if (until <= now()) return;
    const timer = setTimeout(() => tick((n) => n + 1), until - now() + 50);
    return () => clearTimeout(timer);
  }, [until, now]);

  const note = useCallback(
    (error: unknown) => {
      if (error instanceof ApiError && error.status === 429 && error.retryAfterSeconds !== null) {
        setUntil(now() + error.retryAfterSeconds * 1000);
      }
    },
    [now],
  );

  const blocked = until > now();
  return { blocked, waitSeconds: blocked ? Math.ceil((until - now()) / 1000) : 0, note };
}

/** "in 45 seconds" / "in 3 minutes" / "in 2 hours", for a fixed (not ticking) message. */
export function waitPhrase(seconds: number): string {
  if (seconds < 60) return `in ${seconds} seconds`;
  if (seconds < 3600) return `in ${Math.ceil(seconds / 60)} minutes`;
  return `in ${Math.ceil(seconds / 3600)} hours`;
}

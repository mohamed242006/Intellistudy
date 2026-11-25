/**
 * Cross-tab coordination (gate GF0A-11).
 *
 * The backend rotates the refresh token on every use and revokes the whole session family if an already-rotated token
 * is presented again (contract RT-05). Two tabs refreshing at the same instant with the same cookie would therefore
 * sign the user out everywhere. Refreshes run under a Web Lock, so each tab sends the cookie the previous refresh set.
 * Where Web Locks are unavailable, refreshes are still single-flight within the tab (the residual cross-tab race is
 * documented in docs/F0A_GATE.md).
 *
 * Sign-out is broadcast so other tabs drop their in-memory token at once.
 */

export const REFRESH_LOCK = "intellistudy-refresh";
export const AUTH_CHANNEL = "intellistudy-auth";

type LockManagerLike = {
  request<T>(name: string, options: { mode: "exclusive" }, callback: () => Promise<T>): Promise<T>;
};

export async function withRefreshLock<T>(task: () => Promise<T>): Promise<T> {
  const locks: LockManagerLike | undefined =
    typeof navigator !== "undefined" ? (navigator as Navigator & { locks?: LockManagerLike }).locks : undefined;
  if (locks && typeof locks.request === "function") {
    return locks.request(REFRESH_LOCK, { mode: "exclusive" }, task);
  }
  return task();
}

type AuthMessage = { type: "signed-out" };

function channel(): BroadcastChannel | null {
  return typeof BroadcastChannel === "function" ? new BroadcastChannel(AUTH_CHANNEL) : null;
}

export function broadcastSignOut(): void {
  const ch = channel();
  if (!ch) return;
  ch.postMessage({ type: "signed-out" } satisfies AuthMessage);
  ch.close();
}

/** Calls `onSignedOut` when another tab signs out. Returns an unsubscribe function. */
export function onSignOutElsewhere(onSignedOut: () => void): () => void {
  const ch = channel();
  if (!ch) return () => undefined;
  ch.onmessage = (event: MessageEvent<AuthMessage>) => {
    if (event.data?.type === "signed-out") onSignedOut();
  };
  return () => ch.close();
}

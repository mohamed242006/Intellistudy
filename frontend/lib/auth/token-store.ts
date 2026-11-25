/**
 * The access token lives here, in module memory, and nowhere else (contract JWT-07; gate GF0A-07): never in web
 * storage, cookies set by JavaScript or URLs. A page reload loses it; the session is restored by
 * one refresh through the HttpOnly cookie, which JavaScript can never read.
 */

type Listener = () => void;

let accessToken: string | null = null;
let expiresAt: number | null = null; // epoch ms
const listeners = new Set<Listener>();

function notify(): void {
  for (const listener of listeners) listener();
}

export const tokenStore = {
  get(): string | null {
    return accessToken;
  },
  expiresAt(): number | null {
    return expiresAt;
  },
  set(token: string, expiresInSeconds: number, now: number = Date.now()): void {
    accessToken = token;
    expiresAt = now + expiresInSeconds * 1000;
    notify();
  },
  clear(): void {
    if (accessToken === null && expiresAt === null) return;
    accessToken = null;
    expiresAt = null;
    notify();
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

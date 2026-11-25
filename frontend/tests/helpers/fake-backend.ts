/**
 * A scripted stand-in for the FastAPI auth endpoints, returning responses in the backend's real shapes
 * (backend/app/api/v1/auth.py, core/errors.py). Tests queue responses per "METHOD /path" and inspect the calls.
 */
import { vi } from "vitest";

export type Call = { method: string; path: string; search?: string; headers: Record<string, string>; body: unknown; credentials: RequestCredentials | undefined };

type Reply = (url: URL, init: RequestInit) => Response | Promise<Response>;

export function problem(status: number, code: string, detail?: string, headers: Record<string, string> = {}): Response {
  const body: Record<string, unknown> = { type: `about:blank#${code}`, title: "x", status, request_id: "r" };
  if (detail) body.detail = detail;
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/problem+json", ...headers } });
}

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

export const TOKEN = (n = 1) => ({ access_token: `access-token-${n}`, token_type: "bearer", expires_in: 900 });
export const USER = { id: "u-1", email: "student@example.org", name: "Test Student", role: "STUDENT", created_at: "2026-11-25T10:00:00Z" };

export function fakeBackend() {
  const queues = new Map<string, Reply[]>();
  const patterns: [RegExp, Reply][] = [];
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    const key = `${method} ${url.pathname.replace(/^\/api\/v1/, "")}`;
    const headers = Object.fromEntries(Object.entries((init.headers ?? {}) as Record<string, string>));
    calls.push({ method, path: key.split(" ")[1] ?? "", search: url.search, headers, body: init.body ? JSON.parse(String(init.body)) : undefined, credentials: init.credentials });
    const queue = queues.get(key);
    const reply = (queue && queue.length > 1 ? queue.shift() : queue?.[0]) ?? patterns.find(([re]) => re.test(key))?.[1];
    if (!reply) throw new Error(`unexpected request ${key}`);
    return reply(url, init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    fetchMock,
    /** Queue replies for "METHOD /path"; the last one repeats. */
    on(key: string, ...replies: Reply[]) {
      queues.set(key, replies);
      return this;
    },
    /** Fallback reply for every "METHOD /path" matching the pattern (exact keys win). */
    match(pattern: RegExp, reply: Reply) {
      patterns.push([pattern, reply]);
      return this;
    },
    count(key: string) {
      return calls.filter((c) => `${c.method} ${c.path}` === key).length;
    },
  };
}

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiRequest, onSessionExpired } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { tokenStore } from "@/lib/auth/token-store";
import { fakeBackend, json, problem, TOKEN, USER } from "../helpers/fake-backend";

beforeEach(() => tokenStore.clear());
afterEach(() => tokenStore.clear());

describe("GF0A-07 token store", () => {
  it("GF0A-07 keeps the access token in memory only and never writes web storage", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    tokenStore.set("secret-access-token", 900, 1_000);
    expect(tokenStore.get()).toBe("secret-access-token");
    expect(tokenStore.expiresAt()).toBe(901_000);
    tokenStore.clear();
    expect(tokenStore.get()).toBeNull();
    expect(setItem).not.toHaveBeenCalled();
    expect(window.localStorage.length + window.sessionStorage.length).toBe(0);
    expect(document.cookie).not.toContain("secret-access-token");
  });
});

describe("GF0A-08 authorization header", () => {
  it("GF0A-08 is sent only when a token exists, and protected calls omit cookies", async () => {
    const backend = fakeBackend().on("GET /auth/me", () => json(200, USER));
    await apiRequest("/auth/me", { auth: false });
    tokenStore.set("t-1", 900);
    await apiRequest("/auth/me");
    expect(backend.calls[0]!.headers.Authorization).toBeUndefined();
    expect(backend.calls[1]!.headers.Authorization).toBe("Bearer t-1");
    expect(backend.calls[1]!.credentials).toBe("omit");
  });
});

describe("GF0A-09 one refresh, one retry", () => {
  it("GF0A-09 retries a 401 once after a successful refresh", async () => {
    tokenStore.set("old", 900);
    const backend = fakeBackend()
      .on("GET /auth/me", () => problem(401, "session_invalid"), () => json(200, USER))
      .on("POST /auth/refresh", () => json(200, TOKEN(2)));
    await expect(apiRequest("/auth/me")).resolves.toEqual(USER);
    expect(backend.count("GET /auth/me")).toBe(2);
    expect(backend.count("POST /auth/refresh")).toBe(1);
    const refresh = backend.calls.find((c) => c.path === "/auth/refresh")!;
    expect(refresh.headers["X-Requested-With"]).toBe("IntelliStudy");
    expect(refresh.headers.Authorization).toBeUndefined();
    expect(refresh.credentials).toBe("same-origin");
    expect(backend.calls.at(-1)!.headers.Authorization).toBe("Bearer access-token-2");
  });

  it("GF0A-09 a second 401 ends the session and reports expiry", async () => {
    tokenStore.set("old", 900);
    const expired = vi.fn();
    const stop = onSessionExpired(expired);
    const backend = fakeBackend()
      .on("GET /auth/me", () => problem(401, "session_invalid"))
      .on("POST /auth/refresh", () => json(200, TOKEN(2)));
    await expect(apiRequest("/auth/me")).rejects.toMatchObject({ kind: "session_expired" });
    expect(backend.count("GET /auth/me")).toBe(2);
    expect(backend.count("POST /auth/refresh")).toBe(1);
    expect(tokenStore.get()).toBeNull();
    expect(expired).toHaveBeenCalledTimes(1);
    stop();
  });

  it("GF0A-09 a failed refresh ends the session without retrying", async () => {
    tokenStore.set("old", 900);
    const backend = fakeBackend()
      .on("GET /auth/me", () => problem(401, "session_invalid"))
      .on("POST /auth/refresh", () => problem(401, "session_invalid"));
    await expect(apiRequest("/auth/me")).rejects.toMatchObject({ kind: "session_expired" });
    expect(backend.count("GET /auth/me")).toBe(1);
    expect(tokenStore.get()).toBeNull();
  });
});

describe("GF0A-10 concurrent 401s", () => {
  it("GF0A-10 share one refresh operation", async () => {
    tokenStore.set("old", 900);
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const seen = new Set<string>();
    const backend = fakeBackend()
      .on("GET /auth/me", () => json(200, USER))
      .on("POST /auth/refresh", async () => {
        await gate;
        return json(200, TOKEN(2));
      });
    backend.fetchMock.mockImplementation(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const path = new URL(String(input), "http://localhost").pathname;
      const auth = (init.headers as Record<string, string>).Authorization;
      backend.calls.push({ method: init.method ?? "GET", path, headers: init.headers as Record<string, string>, body: undefined, credentials: init.credentials });
      if (path.endsWith("/auth/refresh")) {
        await gate;
        return json(200, TOKEN(2));
      }
      seen.add(auth ?? "");
      return auth === "Bearer access-token-2" ? json(200, USER) : problem(401, "session_invalid");
    });
    const requests = [apiRequest("/a"), apiRequest("/b"), apiRequest("/c")];
    await vi.waitFor(() => expect(backend.calls.filter((c) => !c.path.endsWith("/refresh")).length).toBe(3));
    release();
    await expect(Promise.all(requests)).resolves.toHaveLength(3);
    expect(backend.calls.filter((c) => c.path.endsWith("/auth/refresh")).length).toBe(1);
    expect(seen).toEqual(new Set(["Bearer old", "Bearer access-token-2"]));
  });
});

describe("GF0A-13 error mapping", () => {
  it("GF0A-13 maps backend problem codes to typed errors without exposing internals", async () => {
    const cases: [Response, Record<string, unknown>][] = [
      [problem(422, "validation_error", "The request is not valid."), { kind: "validation", field: null, userMessage: null }],
      [problem(422, "weak_password", "This password is too common."), { kind: "validation", field: "password", userMessage: "This password is too common." }],
      [problem(422, "invalid_email", "Enter a valid email address."), { kind: "validation", field: "email" }],
      [problem(409, "registration_rejected", "Registration could not be completed with these details."), { kind: "registration_rejected" }],
      [problem(429, "rate_limited", "Too many requests.", { "retry-after": "42" }), { kind: "rate_limited", retryAfterSeconds: 42 }],
      [problem(429, "rate_limited"), { kind: "rate_limited", retryAfterSeconds: null }],
      [problem(403, "csrf_rejected", "Forbidden."), { kind: "forbidden" }],
      [new Response("Traceback (most recent call last): secret internals", { status: 500 }), { kind: "server", userMessage: null }],
    ];
    for (const [response, expected] of cases) {
      fakeBackend().on("POST /auth/register", () => response.clone());
      const error = await apiRequest("/auth/register", { method: "POST", body: {}, auth: false }).catch((e: unknown) => e);
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject(expected);
      expect(String((error as ApiError).userMessage ?? "")).not.toContain("Traceback");
    }
  });

  it("GF0A-13 login 401 is invalid_credentials, and a failed fetch is a network error", async () => {
    fakeBackend().on("POST /auth/login", () => problem(401, "invalid_credentials", "Invalid email or password."));
    await expect(apiRequest("/auth/login", { method: "POST", body: {}, auth: false, login: true })).rejects.toMatchObject({ kind: "invalid_credentials" });
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(apiRequest("/auth/me", { auth: false })).rejects.toMatchObject({ kind: "network" });
  });
});

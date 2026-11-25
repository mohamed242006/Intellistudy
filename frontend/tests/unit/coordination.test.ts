import { afterEach, describe, expect, it, vi } from "vitest";
import { broadcastSignOut, onSignOutElsewhere, REFRESH_LOCK } from "@/lib/auth/coordination";
import { refreshSession } from "@/lib/auth/refresh";
import { tokenStore } from "@/lib/auth/token-store";
import { fakeBackend, json, TOKEN } from "../helpers/fake-backend";

afterEach(() => tokenStore.clear());

describe("GF0A-11 cross-tab coordination", () => {
  it("GF0A-11 runs the refresh under an exclusive Web Lock when navigator.locks exists", async () => {
    const request = vi.fn(async (_name: string, _opts: unknown, task: () => Promise<unknown>) => task());
    vi.stubGlobal("navigator", { ...navigator, locks: { request } });
    fakeBackend().on("POST /auth/refresh", () => json(200, TOKEN(7)));
    await expect(refreshSession()).resolves.toBe(true);
    expect(request).toHaveBeenCalledWith(REFRESH_LOCK, { mode: "exclusive" }, expect.any(Function));
    expect(tokenStore.get()).toBe("access-token-7");
  });

  it("GF0A-11 falls back to an in-tab single flight without Web Locks", async () => {
    vi.stubGlobal("navigator", { ...navigator, locks: undefined });
    const backend = fakeBackend().on("POST /auth/refresh", () => json(200, TOKEN(8)));
    const [a, b] = await Promise.all([refreshSession(), refreshSession()]);
    expect([a, b]).toEqual([true, true]);
    expect(backend.count("POST /auth/refresh")).toBe(1);
  });

  it("GF0A-11 broadcasts sign-out to other tabs", async () => {
    const received = vi.fn();
    const stop = onSignOutElsewhere(received);
    broadcastSignOut();
    await vi.waitFor(() => expect(received).toHaveBeenCalledTimes(1));
    stop();
  });
});

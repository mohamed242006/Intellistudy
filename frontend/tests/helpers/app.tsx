/** Render a protected F0-B page as the app does: RequireAuth → shell → page, over the scripted backend. */
import type { ReactNode } from "react";
import ProtectedLayout from "@/app/(app)/layout";
import RailLayout from "@/app/(app)/(rail)/layout";
import SidebarLayout from "@/app/(app)/(sidebar)/layout";
import { fakeBackend, json, TOKEN, USER } from "./fake-backend";
import { nav } from "./navigation";
import { renderWithProviders, testQueryClient } from "./render";

export function signedInBackend() {
  return fakeBackend().on("POST /auth/refresh", () => json(200, TOKEN())).on("GET /auth/me", () => json(200, USER));
}

export function renderPage(ui: ReactNode, { shell = "sidebar", path = "/", search = "", params = {} }: { shell?: "sidebar" | "rail"; path?: string; search?: string; params?: Record<string, string> } = {}) {
  nav.reset(path, search, params);
  const Shell = shell === "sidebar" ? SidebarLayout : RailLayout;
  return renderWithProviders(
    <ProtectedLayout>
      <Shell>{ui}</Shell>
    </ProtectedLayout>,
    testQueryClient(),
  );
}

/** A promise the test resolves later, to hold a request in flight. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

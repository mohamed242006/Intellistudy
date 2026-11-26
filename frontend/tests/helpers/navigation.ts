import { useSyncExternalStore } from "react";
import { vi } from "vitest";

const listeners = new Set<() => void>();
let version = 0;
function emit() {
  version += 1;
  for (const listener of listeners) listener();
}

/** State behind the next/navigation mock used by component tests. */
export const nav = {
  pathname: "/signin",
  search: new URLSearchParams(),
  params: {} as Record<string, string>,
  /** When true (opt-in, F1 tests), push/replace/back really change pathname and search and re-render subscribers. */
  live: false,
  history: [] as string[],
  replace: vi.fn<(href: string, options?: unknown) => void>(),
  push: vi.fn<(href: string, options?: unknown) => void>(),
  back: vi.fn<() => void>(),
  redirect: vi.fn<(href: string) => void>(),
  reset(pathname = "/signin", search = "", params: Record<string, string> = {}) {
    nav.pathname = pathname;
    nav.search = new URLSearchParams(search);
    nav.params = params;
    nav.live = false;
    nav.history = [];
    nav.replace.mockReset();
    nav.push.mockReset();
    nav.back.mockReset();
    nav.redirect.mockReset();
    nav.push.mockImplementation((href) => go(href, "push"));
    nav.replace.mockImplementation((href) => go(href, "replace"));
    nav.back.mockImplementation(() => {
      if (!nav.live || nav.history.length === 0) return;
      set(nav.history.pop()!);
    });
    emit();
  },
};

function current(): string {
  const q = nav.search.toString();
  return q ? `${nav.pathname}?${q}` : nav.pathname;
}

function set(href: string) {
  const url = new URL(href, "http://localhost");
  nav.pathname = url.pathname;
  nav.search = new URLSearchParams(url.search);
  emit();
}

function go(href: string, mode: "push" | "replace") {
  if (!nav.live) return;
  if (mode === "push") nav.history.push(current());
  set(href);
}

function useNavVersion() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => version,
  );
}

export const navigationMock = () => ({
  useRouter: () => ({ replace: nav.replace, push: nav.push, prefetch: vi.fn(), back: nav.back, refresh: vi.fn() }),
  usePathname: () => {
    useNavVersion();
    return nav.pathname;
  },
  useSearchParams: () => {
    useNavVersion();
    return nav.search;
  },
  useParams: () => nav.params,
  redirect: (href: string) => nav.redirect(href),
});

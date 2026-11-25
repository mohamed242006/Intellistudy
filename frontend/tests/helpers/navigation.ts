import { vi } from "vitest";

/** State behind the next/navigation mock used by component tests. */
export const nav = {
  pathname: "/signin",
  search: new URLSearchParams(),
  replace: vi.fn<(href: string) => void>(),
  push: vi.fn<(href: string) => void>(),
  reset(pathname = "/signin", search = "") {
    nav.pathname = pathname;
    nav.search = new URLSearchParams(search);
    nav.replace.mockReset();
    nav.push.mockReset();
  },
};

export const navigationMock = () => ({
  useRouter: () => ({ replace: nav.replace, push: nav.push, prefetch: vi.fn(), back: vi.fn(), refresh: vi.fn() }),
  usePathname: () => nav.pathname,
  useSearchParams: () => nav.search,
});

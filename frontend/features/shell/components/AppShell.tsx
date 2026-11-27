"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { NavItem, RailItem } from "@/design-system/components/NavItem";
import { Wordmark } from "@/design-system/compositions/Wordmark";
import type { IconName } from "@/design-system/icons/placeholders";
import { FIGMA, PROVISIONAL } from "../strings";
import { UserMenu } from "./UserMenu";

/**
 * Application shells (gate GF0B-01; UI §6.1-6.3).
 * - Sidebar (264, Dashboard and Upload) and Rail (72, Workspace) at 1024 px and wider, as drawn.
 * - Only destinations that exist are listed: Dashboard, Courses (`/#courses`, no Courses frame exists) and Settings
 *   (account: password, devices). Analytics, Personalised exam and Data & privacy have no backend and stay hidden.
 * - Below 1024 px (no approved design): a provisional top bar with the same links and the account menu.
 */
type Destination = { key: "dashboard" | "courses" | "settings"; href: string; label: string; icon: IconName };

const DESTINATIONS: readonly Destination[] = [
  { key: "dashboard", href: "/", label: FIGMA.dashboard, icon: "home" },
  { key: "courses", href: "/#courses", label: FIGMA.courses, icon: "book" },
  { key: "settings", href: "/settings", label: FIGMA.settings, icon: "sliders" },
];

function activeKey(pathname: string | null): Destination["key"] {
  if (pathname && /^\/settings(\/|$)/.test(pathname)) return "settings";
  return pathname && /^\/(courses|quizzes|attempts|summaries)(\/|$)/.test(pathname) ? "courses" : "dashboard";
}

function SkipLink() {
  return (
    <a href="#main" className="sr-only z-[70] rounded-md bg-surface px-4 py-3 text-label text-fg focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
      {PROVISIONAL.skipToContent}
    </a>
  );
}

function TopBar({ current }: { current: Destination["key"] }) {
  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-surface px-4 py-2 lg:hidden">
      <Link href="/" aria-label={PROVISIONAL.homeLink} className="rounded-md">
        <Wordmark />
      </Link>
      <nav aria-label={PROVISIONAL.mainNav} className="order-3 w-full sm:order-none sm:w-auto sm:flex-1">
        <ul className="flex gap-1">
          {DESTINATIONS.map((d) => (
            <li key={d.key}>
              <Link
                href={d.href}
                aria-current={d.key === current ? "page" : undefined}
                className={`flex h-control-md items-center rounded-md px-3 text-label ${d.key === current ? "bg-accent-subtle text-accent-fg" : "text-fg-secondary hover:bg-subtle"}`}
              >
                {d.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <div className="ml-auto w-11 sm:ml-0">
        <UserMenu variant="avatar" />
      </div>
    </header>
  );
}

export function SidebarShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const current = activeKey(pathname);
  return (
    <div className="min-h-screen lg:flex">
      <SkipLink />
      <aside className="sticky top-0 hidden h-screen w-sidebar shrink-0 flex-col gap-1 overflow-y-auto border-r border-line bg-surface px-4 py-6 lg:flex">
        <Link href="/" aria-label={PROVISIONAL.homeLink} className="flex h-14 w-[132px] items-center rounded-md">
          <Wordmark />
        </Link>
        <nav aria-label={PROVISIONAL.mainNav}>
          <ul className="flex flex-col gap-1">
            {DESTINATIONS.map((d) => (
              <li key={d.key}>
                <NavItem href={d.href} icon={d.icon} label={d.label} selected={d.key === current} />
              </li>
            ))}
          </ul>
        </nav>
        <div className="flex-1" />
        <UserMenu variant="card" />
      </aside>
      <TopBar current={current} />
      <main id="main" tabIndex={-1} className="min-w-0 flex-1 outline-none">
        {/* page entrance (motion/slow fade + 4px rise; off under reduced motion), replayed on each route */}
        <div key={pathname} className="motion-enter">
          {children}
        </div>
      </main>
    </div>
  );
}

export function RailShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const current = activeKey(pathname);
  return (
    <div className="min-h-screen lg:flex">
      <SkipLink />
      <aside className="sticky top-0 hidden h-screen w-rail shrink-0 flex-col items-center gap-1 border-r border-line bg-surface py-6 lg:flex">
        <Link href="/" aria-label={PROVISIONAL.homeLink} className="flex h-14 w-8 items-center rounded-md">
          <Wordmark markOnly />
        </Link>
        <nav aria-label={PROVISIONAL.mainNav}>
          <ul className="flex flex-col items-center gap-1">
            {DESTINATIONS.map((d) => (
              <li key={d.key}>
                <RailItem href={d.href} icon={d.icon} label={d.label} selected={d.key === current} />
              </li>
            ))}
          </ul>
        </nav>
        <div className="flex-1" />
        <div className="w-11">
          <UserMenu variant="avatar" />
        </div>
      </aside>
      <TopBar current={current} />
      <main id="main" tabIndex={-1} className="min-w-0 flex-1 outline-none">
        {/* page entrance (motion/slow fade + 4px rise; off under reduced motion), replayed on each route */}
        <div key={pathname} className="motion-enter">
          {children}
        </div>
      </main>
    </div>
  );
}

"use client";

import { usePathname } from "next/navigation";
import { TabLink } from "@/design-system/components/Tab";
import { Wordmark } from "@/design-system/compositions/Wordmark";
import { Icon } from "@/design-system/icons/Icon";
import type { IconName } from "@/design-system/icons/placeholders";
import { FIGMA } from "../strings";

const TRUST_ICONS: readonly IconName[] = ["book", "file", "lock"];

/**
 * AuthShell (UI §6.1, §8.1.4). Brand panel 640 wide (`accent/subtle`, padding 80, gap 32) + form side filling the rest,
 * with the Auth card centred: 440 wide, padding 40, gap 24, radius 16, `bg/surface`, 1 px `border/default`, `shadow/md`.
 * Below 1080 px (640 + 440) panel and form stack, so 200% zoom stays usable; this reflow is provisional (UI C16).
 */
export function AuthShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const onSignUp = pathname === "/signup";
  return (
    <div className="flex min-h-screen flex-col bg-canvas min-[1080px]:flex-row">
      <section
        aria-label="About IntelliStudy"
        className="flex w-full shrink-0 flex-col gap-8 bg-accent-subtle p-10 min-[1080px]:w-auth-brand min-[1080px]:p-20"
      >
        <Wordmark />
        <p className="text-display text-fg">{FIGMA.brandHeadline}</p>
        <p className="text-body-lg text-fg-secondary">{FIGMA.brandSubcopy}</p>
        <ul className="flex flex-col gap-4">
          {FIGMA.trustPoints.map((point, index) => (
            <li key={point} className="flex items-start gap-3 text-body text-fg">
              <Icon name={TRUST_ICONS[index] ?? "book"} size={20} className="mt-0.5" />
              <span>{point}</span>
            </li>
          ))}
        </ul>
      </section>
      <main className="flex flex-1 items-center justify-center p-6">
        <div
          data-testid="auth-card"
          className="flex w-full max-w-auth-card flex-col gap-6 rounded-xl border border-line bg-surface p-10 shadow-md"
        >
          <nav aria-label="Account" className="flex">
            <TabLink href="/signin" selected={!onSignUp}>
              {FIGMA.tabSignIn}
            </TabLink>
            <TabLink href="/signup" selected={onSignUp}>
              {FIGMA.tabCreateAccount}
            </TabLink>
          </nav>
          {children}
        </div>
      </main>
    </div>
  );
}

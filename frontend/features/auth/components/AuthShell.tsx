"use client";

import Image from "next/image";
import { usePathname } from "next/navigation";
import { BRAND } from "@/design-system/brand";
import { TabLink } from "@/design-system/components/Tab";
import { Wordmark } from "@/design-system/compositions/Wordmark";
import { Icon } from "@/design-system/icons/Icon";
import type { IconName } from "@/design-system/icons/placeholders";
import { FIGMA } from "../strings";

const TRUST_ICONS: readonly IconName[] = ["checkCircle", "lock", "target"];

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
        className="relative isolate flex w-full shrink-0 flex-col gap-8 overflow-hidden bg-accent-subtle p-10 min-[1080px]:w-auth-brand min-[1080px]:p-20"
      >
        {/* Decorative background (placeholder, design-system/brand.ts) under an overlay: text contrast never depends on it */}
        <Image src={BRAND.backgroundSrc} alt="" fill priority sizes="(min-width: 1080px) 640px, 100vw" className="-z-20 object-cover" />
        <div aria-hidden="true" className="absolute inset-0 -z-10 bg-accent-subtle/85" />
        <Wordmark />
        <p className="motion-enter text-display text-fg">{FIGMA.brandHeadline}</p>
        <p className="text-body-lg text-fg-secondary">{FIGMA.brandSubcopy}</p>
        <ul className="flex flex-col gap-4">
          {FIGMA.trustPoints.map((point, index) => (
            <li key={point} className="flex items-start gap-3 text-body text-fg">
              <Icon name={TRUST_ICONS[index] ?? "book"} size={20} className="mt-0.5 shrink-0 text-accent-fg" />
              <span>{point}</span>
            </li>
          ))}
        </ul>
      </section>
      <main className="flex flex-1 items-center justify-center p-6">
        <div
          data-testid="auth-card"
          className="motion-enter flex w-full max-w-auth-card flex-col gap-6 rounded-xl border border-line bg-surface p-6 sm:p-10"
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

import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Card (UI §7.9): V, padding 24, gap 12, radius 16, `bg/surface`, 1 px `border/default`. Title `text/title`,
 * Description `text/body-sm` secondary, status line `text/caption-strong`, meta `text/caption` secondary.
 * Hover: `border/strong` + `shadow/md`; Focus: 2 px ring (global). The whole card is a link (UI §7.9 recommendation).
 */
export type CardStatusTone = "success" | "accent" | "danger" | "neutral";

const STATUS: Record<CardStatusTone, string> = {
  success: "text-success-fg",
  accent: "text-accent-fg",
  danger: "text-danger-fg",
  neutral: "text-fg-secondary",
};

export function Card({ href, title, description, status, meta, footer }: {
  href: string;
  title: string;
  description?: string | null;
  status?: { text: string; tone: CardStatusTone } | null;
  meta?: string | null;
  footer?: ReactNode;
}) {
  return (
    <Link
      href={href}
      className="flex min-h-[162px] min-w-0 flex-col gap-3 rounded-xl border border-line bg-surface p-6 transition-shadow hover:border-line-strong hover:shadow-md"
    >
      <span className="text-title break-words text-fg">{title}</span>
      {description ? <span className="text-body-sm break-words text-fg-secondary">{description}</span> : null}
      {status ? <span className={`text-caption-strong ${STATUS[status.tone]}`}>{status.text}</span> : null}
      {meta ? <span className="text-caption text-fg-secondary">{meta}</span> : null}
      {footer}
    </Link>
  );
}

/** Card Loading (UI §7.9): three skeleton bars (`bg/subtle`, radius 4: 200/280/240 × 16), height 122, no shimmer. */
export function CardSkeleton() {
  return (
    <div aria-hidden="true" data-card-loading className="flex h-[122px] flex-col gap-3 rounded-xl border border-line bg-surface p-6">
      <span className="h-4 w-[200px] max-w-full rounded-sm bg-subtle motion-pulse" />
      <span className="h-4 w-[280px] max-w-full rounded-sm bg-subtle motion-pulse" />
      <span className="h-4 w-[240px] max-w-full rounded-sm bg-subtle motion-pulse" />
    </div>
  );
}

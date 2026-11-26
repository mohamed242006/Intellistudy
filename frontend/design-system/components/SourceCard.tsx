"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { Icon } from "../icons/Icon";

/** Passages longer than this are clamped to 5 lines with a Show more / Show less toggle (spec §4.11.1: max 5 lines). */
export const CLAMP_CHARS = 280;

/**
 * SourceCard (spec §4.11.1): padding 16, gap 12, radius 12; header (index badge `[n]` + file name `text/label`) →
 * location `text/caption` → passage (`bg/subtle` block with a 2px accent quote bar, `text/body-sm`).
 * Selected: `accent/subtle` fill, 2 px `accent/default` stroke, solid badge. Everything is plain text; line breaks are
 * kept; only tokens that cannot fit wrap mid-word (`overflow-wrap: anywhere`), so names never split letter by letter.
 * `clamp` shortens long passages behind an accessible toggle. `href` adds "Open file" (the file in its course).
 */
export function SourceCard({ number, fileName, location, passage, selected = false, clamp = false, href, openLabel = "Open file", moreLabel = "Show more", lessLabel = "Show less" }: {
  number?: number;
  fileName: string;
  location: string;
  passage: string;
  selected?: boolean;
  clamp?: boolean;
  href?: string;
  openLabel?: string;
  moreLabel?: string;
  lessLabel?: string;
}) {
  const passageId = useId();
  const [expanded, setExpanded] = useState(false);
  const long = clamp && passage.length > CLAMP_CHARS;
  return (
    <div
      data-selected={selected || undefined}
      className={`flex min-w-0 flex-col gap-3 rounded-lg p-4 ${selected ? "border-2 border-accent bg-accent-subtle" : "border border-line bg-surface"}`}
    >
      <div className="flex min-w-0 items-start gap-2">
        {number !== undefined ? (
          <span
            aria-hidden="true"
            className={`inline-flex h-[22px] min-w-6 shrink-0 items-center justify-center rounded-sm border px-1 text-caption-strong ${selected ? "border-accent bg-accent text-fg-on-accent" : "border-accent-subtle-border bg-accent-subtle text-accent-fg"}`}
          >
            [{number}]
          </span>
        ) : null}
        <span className="min-w-0 text-label wrap-anywhere text-fg">{fileName}</span>
      </div>
      <p className="-mt-2 text-caption text-fg-secondary">{location}</p>
      <div className="flex flex-col items-start gap-1">
        <div className="w-full rounded-md border-l-2 border-accent bg-subtle px-3 py-2">
          {/* the clamp sits on the unpadded text box, so no part of a sixth line shows through the padding */}
          <p id={passageId} className={`text-body-sm break-words whitespace-pre-line text-fg ${long && !expanded ? "line-clamp-5" : ""}`}>
            {passage}
          </p>
        </div>
        {long ? (
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={passageId}
            onClick={() => setExpanded((open) => !open)}
            className="min-h-11 rounded-md px-2 text-label text-accent-fg hover:bg-accent-subtle"
          >
            {expanded ? lessLabel : moreLabel}
          </button>
        ) : null}
      </div>
      {href ? (
        <Link href={href} className="inline-flex min-h-11 items-center gap-2 self-start rounded-md px-2 text-label text-accent-fg hover:bg-accent-subtle">
          <Icon name="external" size={16} />
          <span>
            {openLabel}
            <span className="sr-only">: {fileName}</span>
          </span>
        </Link>
      ) : null}
    </div>
  );
}

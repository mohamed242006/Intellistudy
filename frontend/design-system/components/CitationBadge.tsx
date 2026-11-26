import type { Ref } from "react";

/**
 * CitationBadge (UI §7.6), Inline size: pill 24×22 (wider for numbers above 9), radius 4, `text/caption-strong`, literal
 * brackets "[n]". Default `accent/subtle` + `accent/subtle-border`; Hover `accent/subtle-border` fill + `accent/default`
 * stroke; Active solid `accent/default` with on-accent text; Focus 2 px ring. The visible pill stays Inline, but the
 * hit area is 44×44 (UI §18 D-6, D-22) through a transparent pseudo-element. A `button` with a descriptive name.
 */
export function CitationBadge({ number, label, active, onSelect, ref }: {
  number: number;
  /** Accessible name, for example "Source 1: lecture.pdf, p. 3". */
  label: string;
  active: boolean;
  onSelect: (trigger: HTMLButtonElement) => void;
  ref?: Ref<HTMLButtonElement>;
}) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      aria-pressed={active}
      data-citation={number}
      onClick={(event) => onSelect(event.currentTarget)}
      className={[
        "relative mx-0.5 inline-flex h-[22px] min-w-6 items-center justify-center rounded-sm border px-1 align-baseline text-caption-strong",
        "before:absolute before:top-1/2 before:left-1/2 before:size-11 before:-translate-x-1/2 before:-translate-y-1/2 before:content-['']",
        active
          ? "border-accent bg-accent text-fg-on-accent"
          : "border-accent-subtle-border bg-accent-subtle text-accent-fg hover:border-accent hover:bg-accent-subtle-border",
      ].join(" ")}
    >
      [{number}]
    </button>
  );
}

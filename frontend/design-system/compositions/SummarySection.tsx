"use client";

import { useId, useState, type ReactNode } from "react";
import { Icon } from "../icons/Icon";

/**
 * Summary section (UI §7.23): V, radius 12, `bg/surface`, 1 px `border/default`. Header 60 high, padding 8/16/8/8:
 * a 44×44 disclosure toggle (chevron placeholder) + title `text/title` + count caption; body (expanded) gap 12,
 * padding 4/24/24/64, one bullet row per statement (6×6 dot in `text/tertiary`). The whole header is the toggle
 * (`aria-expanded`), and the heading text is the button's name.
 */
export function SummarySection({ heading, caption, statements, defaultExpanded, headingLevel = 2 }: {
  heading: string;
  caption: string;
  statements: ReactNode[];
  defaultExpanded: boolean;
  /** 3 when the sections sit under a per-file heading (combined summaries). */
  headingLevel?: 2 | 3;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const Heading = headingLevel === 3 ? "h3" : "h2";
  const bodyId = useId();
  return (
    <section className="rounded-lg border border-line bg-surface">
      <Heading className="m-0">
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={bodyId}
          onClick={() => setExpanded((v) => !v)}
          className="flex min-h-[60px] w-full items-center gap-2 rounded-lg py-2 pr-4 pl-2 text-left hover:bg-subtle"
        >
          <span className="flex size-11 shrink-0 items-center justify-center">
            <Icon name={expanded ? "chevronDown" : "chevronRight"} size={20} />
          </span>
          <span className="min-w-0 flex-1 text-title break-words text-fg">{heading}</span>
          <span className="shrink-0 text-caption text-fg-secondary">{caption}</span>
        </button>
      </Heading>
      <div id={bodyId} hidden={!expanded} className="motion-enter-fast">
        <ul className="flex flex-col gap-3 pt-1 pr-6 pb-6 pl-16 max-md:pl-6">
          {statements.map((statement, index) => (
            <li key={index} className="flex gap-3">
              <span aria-hidden="true" className="flex h-6 w-1.5 shrink-0 items-center">
                <span className="size-1.5 rounded-full bg-fg-tertiary" />
              </span>
              <p className="min-w-0 text-body break-words text-fg">{statement}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

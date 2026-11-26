"use client";

import { useEffect, useRef } from "react";
import { IconButton } from "@/design-system/components/IconButton";
import { Modal } from "@/design-system/components/Modal";
import { SourceCard } from "@/design-system/components/SourceCard";
import { useMediaQuery } from "@/lib/hooks/use-media-query";
import { FIGMA, PROVISIONAL } from "./strings";

/** The verified fields a source may have (SummaryCitation, CitationOut); `context` exists for chat citations only. */
export type SourceItem = { number: number; file_name: string; citation_label: string; passage: string; context?: string };

export const DESKTOP_PANEL_QUERY = "(min-width: 1280px)";

function SourceBody({ source, showContext }: { source: SourceItem; showContext: boolean }) {
  return (
    <div className="flex flex-col gap-4">
      {showContext ? <p className="text-caption-strong text-fg-secondary">{FIGMA.exactPassage}</p> : null}
      <SourceCard number={source.number} fileName={source.file_name} location={source.citation_label} passage={source.passage} selected />
      {showContext && source.context ? (
        <div className="flex flex-col gap-2 rounded-md bg-subtle p-4">
          <p className="text-caption-strong text-fg-secondary">{`${FIGMA.surroundingText} · ${source.citation_label}`}</p>
          <p className="text-body-sm break-words whitespace-pre-line text-fg">{source.context}</p>
        </div>
      ) : null}
    </div>
  );
}

function SourceList({ title, sources, selected, onSelect }: { title: string; sources: readonly SourceItem[]; selected: number | null; onSelect: (n: number, trigger: HTMLButtonElement) => void }) {
  if (sources.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-caption-strong text-fg-secondary">{title}</p>
      <ul className="flex flex-col">
        {sources.map((source) => (
          <li key={source.number}>
            <button
              type="button"
              aria-pressed={selected === source.number}
              onClick={(event) => onSelect(source.number, event.currentTarget)}
              className="flex min-h-11 w-full items-center gap-3 rounded-md px-2 text-left hover:bg-subtle"
            >
              <span
                aria-hidden="true"
                className={`inline-flex h-[22px] min-w-6 shrink-0 items-center justify-center rounded-sm border px-1 text-caption-strong ${selected === source.number ? "border-accent bg-accent text-fg-on-accent" : "border-accent-subtle-border bg-accent-subtle text-accent-fg"}`}
              >
                [{source.number}]
              </span>
              <span className="min-w-0 text-body-sm break-all text-fg-secondary">{`${source.file_name} · ${source.citation_label}`}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Source panel (UI §8.5.4, §8.6.4; gates GF1-09, GF1-10).
 * - Desktop (≥ 1280 px): a non-modal complementary panel. No focus trap; Escape inside it closes it; closing returns
 *   focus to the badge that opened it (`returnFocus`).
 * - Narrower: the provisional bottom sheet (modal: scrim, focus trap, Escape), shown only while a source is selected.
 * `selected` that is not among `sources` shows "This source isn't available" and never another source.
 */
export function SourceView({ sources, selected, listTitle, showContext, onSelect, onClose, returnFocus, alwaysShowPanel }: {
  sources: readonly SourceItem[];
  selected: number | null;
  listTitle: string;
  showContext: boolean;
  onSelect: (n: number, trigger: HTMLButtonElement) => void;
  onClose: () => void;
  /** The badge to focus after closing. */
  returnFocus: () => HTMLElement | null;
  /** Desktop: keep the panel with its source list even when nothing is selected (Summary). */
  alwaysShowPanel: boolean;
}) {
  const desktop = useMediaQuery(DESKTOP_PANEL_QUERY);
  const panel = useRef<HTMLElement>(null);
  const source = selected === null ? null : (sources.find((s) => s.number === selected) ?? null);
  const close = () => {
    const target = returnFocus();
    onClose();
    if (target?.isConnected) requestAnimationFrame(() => target.focus());
  };

  useEffect(() => {
    if (desktop && selected !== null) panel.current?.querySelector<HTMLElement>("h2")?.focus();
  }, [desktop, selected]);

  const body = source ? <SourceBody source={source} showContext={showContext} /> : selected !== null ? <p className="text-body-sm text-fg-secondary">{PROVISIONAL.unavailable}</p> : <p className="text-body-sm text-fg-secondary">{PROVISIONAL.noSelection}</p>;

  if (!desktop) {
    return (
      <Modal variant="sheet" open={selected !== null} title={FIGMA.sourceTitle(selected ?? 0)} onClose={close} closeLabel={PROVISIONAL.closeSource}>
        {body}
      </Modal>
    );
  }
  if (selected === null && !alwaysShowPanel) return null;
  return (
    <aside
      ref={panel}
      aria-label={PROVISIONAL.sourceRegion}
      onKeyDown={(event) => {
        if (event.key === "Escape" && selected !== null) {
          event.preventDefault();
          close();
        }
      }}
      className="flex w-[380px] shrink-0 flex-col gap-4 self-stretch border-l border-line bg-surface px-6 py-8"
    >
      <div className="flex h-11 items-center justify-between gap-2">
        <h2 tabIndex={-1} className="text-title text-fg outline-none">
          {selected === null ? PROVISIONAL.sourceRegion : FIGMA.sourceTitle(selected)}
        </h2>
        {selected !== null ? <IconButton icon="x" label={PROVISIONAL.closeSource} onClick={close} /> : null}
      </div>
      {body}
      <SourceList title={listTitle} sources={sources} selected={selected} onSelect={onSelect} />
    </aside>
  );
}

"use client";

import { useEffect, useId, useRef } from "react";
import { Tag, type TagTone } from "@/design-system/components/Tag";
import { Icon } from "@/design-system/icons/Icon";
import type { DocumentOut } from "@/lib/api/types";
import { formatBytes } from "@/lib/format/format";
import { allState, fileKind, selectAll, selectedCountText, splitName, toggle } from "../selection";
import { EMPTY_CODES, UNSUPPORTED_CODES, isInProgress } from "../status";

export const PICKER_COPY = {
  selectAll: "Select all ready files",
  clear: "Clear selection",
  ready: "Ready",
  processing: "Processing",
  failed: "Processing failed",
  empty: "No readable text",
  unsupported: "Not supported",
  unavailable: "Unavailable",
  noFiles: "This course has no files yet.",
  noReady: "No file is ready yet. Files can be selected once processing has finished.",
  unit: (kind: string, n: number) => (kind === "PPTX" ? `${n} ${n === 1 ? "slide" : "slides"}` : `${n} ${n === 1 ? "page" : "pages"}`),
} as const;

function statusOf(doc: Pick<DocumentOut, "status" | "error_code">): { label: string; tone: TagTone } {
  if (doc.status === "ready") return { label: PICKER_COPY.ready, tone: "success" };
  if (isInProgress(doc.status)) return { label: PICKER_COPY.processing, tone: "accent" };
  if (doc.status === "failed") {
    const code = doc.error_code ?? "";
    if (EMPTY_CODES.has(code)) return { label: PICKER_COPY.empty, tone: "warning" };
    if (UNSUPPORTED_CODES.has(code)) return { label: PICKER_COPY.unsupported, tone: "danger" };
    return { label: PICKER_COPY.failed, tone: "danger" };
  }
  return { label: PICKER_COPY.unavailable, tone: "neutral" };
}

/**
 * Reusable file selection for Summary and Quiz. Every file of the course is listed; only ready ones can be chosen.
 * "Select all ready files" is a tri-state checkbox (checked / unchecked / indeterminate) that never selects a disabled
 * file. Selection order is the reader's order. File names keep their extension visible and truncate the stem; the full
 * name is the checkbox's accessible name. The selected count is announced politely.
 */
export function DocumentPicker({ legend, documents, selected, onChange, disabled = false, hint }: {
  legend: string;
  documents: readonly DocumentOut[];
  selected: readonly string[];
  onChange: (ids: string[]) => void;
  /** While a generation is being submitted. */
  disabled?: boolean;
  /** Guidance shown under the legend (for example why the action is disabled). */
  hint?: string;
}) {
  const id = useId();
  const all = useRef<HTMLInputElement>(null);
  const state = allState(selected, documents);
  const readyCount = documents.filter((d) => d.status === "ready").length;
  const count = selected.length;

  useEffect(() => {
    if (all.current) all.current.indeterminate = state === "some";
  }, [state]);

  return (
    <fieldset className="flex min-w-0 flex-col gap-3" aria-describedby={hint ? `${id}-hint` : undefined} disabled={disabled}>
      <legend className="mb-1 text-label text-fg">{legend}</legend>
      {hint ? (
        <p id={`${id}-hint`} className="-mt-1 text-body-sm text-fg-secondary">
          {hint}
        </p>
      ) : null}
      {documents.length === 0 ? <p className="text-body-sm text-fg-secondary">{PICKER_COPY.noFiles}</p> : null}
      {documents.length > 0 && readyCount === 0 ? <p className="text-body-sm text-fg-secondary">{PICKER_COPY.noReady}</p> : null}
      {readyCount > 0 ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <label className="flex min-h-11 cursor-pointer items-center gap-3 text-label text-fg">
            <input
              ref={all}
              type="checkbox"
              checked={state === "all"}
              onChange={(e) => onChange(e.target.checked ? selectAll(documents) : [])}
              className="size-5 shrink-0 accent-[var(--color-accent)]"
            />
            {PICKER_COPY.selectAll}
          </label>
          <button
            type="button"
            onClick={() => onChange([])}
            disabled={count === 0}
            className="min-h-11 rounded-md px-2 text-label text-accent-fg hover:bg-accent-subtle disabled:cursor-not-allowed disabled:text-disabled-fg disabled:hover:bg-transparent"
          >
            {PICKER_COPY.clear}
          </button>
          <p aria-live="polite" className="ml-auto text-body-sm text-fg-secondary tabular-nums" data-testid="selected-count">
            {selectedCountText(count)}
          </p>
        </div>
      ) : null}
      {documents.length ? (
        <ul className="motion-stagger flex flex-col gap-2">
          {documents.map((doc) => {
            const ready = doc.status === "ready";
            const on = selected.includes(doc.id);
            const status = statusOf(doc);
            const kind = fileKind(doc);
            const { stem, ext } = splitName(doc.file_name);
            const meta = [kind, doc.page_count ? PICKER_COPY.unit(kind, doc.page_count) : null, doc.size_bytes ? formatBytes(doc.size_bytes) : null].filter(Boolean).join(" · ");
            return (
              <li key={doc.id} className="min-w-0">
                <label
                  title={doc.file_name}
                  className={`flex min-h-14 min-w-0 items-center gap-3 rounded-lg border px-3 py-2 transition-colors duration-150 ${
                    on ? "border-accent bg-accent-subtle" : ready ? "cursor-pointer border-line bg-surface hover:border-line-strong" : "cursor-not-allowed border-line bg-subtle"
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={!ready}
                    aria-label={`${doc.file_name}${ready ? "" : `, ${status.label}`}`}
                    onChange={(e) => onChange(toggle(selected, doc.id, e.target.checked, documents))}
                    className="size-5 shrink-0 accent-[var(--color-accent)]"
                  />
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-subtle text-fg-secondary">
                    <Icon name="file" size={18} />
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className={`flex min-w-0 text-label ${ready ? "text-fg" : "text-fg-secondary"}`} aria-hidden="true">
                      <span className="truncate">{stem}</span>
                      <span className="shrink-0">{ext}</span>
                    </span>
                    <span className="text-caption text-fg-secondary">{meta}</span>
                  </span>
                  <span className="shrink-0">
                    <Tag tone={status.tone}>{status.label}</Tag>
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      ) : null}
    </fieldset>
  );
}

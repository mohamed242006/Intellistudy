"use client";

import { Notice } from "@/design-system/components/Notice";
import { SourceCard } from "@/design-system/components/SourceCard";
import { CitationText } from "@/design-system/compositions/CitationText";
import { Icon } from "@/design-system/icons/Icon";
import { PROVISIONAL as SOURCE_COPY } from "@/features/sources/strings";
import type { MessageOut } from "@/lib/api/types";
import { BACKEND_NOTICES, FIGMA, PROVISIONAL } from "../strings";

export type AnswerKind = "answered" | "partial" | "low_confidence" | "refused" | "unknown";

/** The backend's state, never upgraded or downgraded (gate GF1-18). Unknown future states claim nothing. */
export function answerKind(state: string): AnswerKind {
  return state === "answered" || state === "partial" || state === "low_confidence" || state === "refused" ? state : "unknown";
}

export function citedFileCount(message: Pick<MessageOut, "citations">): number {
  return new Set(message.citations.map((c) => c.document_id)).size;
}

function Header({ caption, kind }: { caption: string; kind: AnswerKind | "loading" }) {
  return (
    <div className="flex items-center gap-2" data-kind={kind}>
      <span aria-hidden="true" className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-subtle">
        <Icon name="book" size={16} />
      </span>
      <span className="text-label text-fg">{FIGMA.assistant}</span>
      <span className="text-caption text-fg-secondary">{caption}</span>
    </div>
  );
}

/** The question, as the reader wrote it (normalised by the backend). */
export function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <p className="max-w-[520px] min-w-0 rounded-lg bg-subtle px-4 py-3 text-body break-words whitespace-pre-line text-fg">
        <span className="sr-only">{PROVISIONAL.you}: </span>
        {text}
      </p>
    </div>
  );
}

/** Loading (UI §7.21): "Working", three static skeleton lines (D-14) and the status row; no invented content. */
export function PendingAnswer({ searching }: { searching: string }) {
  return (
    <div className="flex flex-col gap-4" aria-busy="true">
      <Header caption={FIGMA.working} kind="loading" />
      <div aria-hidden="true" className="flex flex-col gap-2">
        <span className="h-4 w-[560px] max-w-full rounded-sm bg-subtle" />
        <span className="h-4 w-[480px] max-w-full rounded-sm bg-subtle" />
        <span className="h-4 w-[320px] max-w-full rounded-sm bg-subtle" />
      </div>
      <p className="flex items-center gap-2 text-body-sm text-fg-secondary">
        <Icon name="loader" size={16} />
        <span>{searching}</span>
      </p>
    </div>
  );
}

/**
 * One assistant answer (UI §7.21; gates GF1-14, GF1-15, GF1-18, GF1-20). Answer text, notices and sources are text.
 * Badges and the SOURCES row open only this message's citations.
 */
export function AssistantMessage({ message, activeNumber, onSelect }: {
  message: MessageOut;
  activeNumber: number | null;
  onSelect: (number: number, trigger: HTMLButtonElement) => void;
}) {
  const kind = answerKind(message.state);
  const labels = new Map(message.citations.map((c) => [c.number, SOURCE_COPY.sourceLabel(c.number, c.file_name, c.citation_label)]));
  const files = citedFileCount(message);
  const lines = message.text.split("\n").map((line) => line.trim()).filter(Boolean);

  if (kind === "refused") {
    const unavailable = message.refusal_reason === "llm_unavailable";
    const withheld = ["uncited_answer", "unsupported_claims", "scope_violation"].includes(message.refusal_reason ?? "");
    const closest = message.nearest[0];
    return (
      <div className="flex flex-col gap-4" data-state="refused">
        <Header caption={unavailable ? PROVISIONAL.unavailableCaption : FIGMA.notFound} kind="refused" />
        <div className="flex flex-col gap-3 rounded-lg border border-line bg-subtle p-4">
          <p className="flex items-start gap-2 text-title text-fg">
            <Icon name="info" size={20} className="mt-0.5" />
            <span>{unavailable ? PROVISIONAL.unavailableTitle : withheld ? PROVISIONAL.withheldTitle : FIGMA.refusedTitle}</span>
          </p>
          <p className="text-body break-words whitespace-pre-line text-fg-secondary">{message.text}</p>
          {closest && !unavailable ? (
            <div className="flex max-w-[360px] flex-col gap-2">
              <p className="text-caption-strong text-fg-secondary">{PROVISIONAL.closestMaterial}</p>
              <SourceCard fileName={closest.file_name} location={closest.citation_label} passage={closest.passage} />
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  const caption = kind === "partial" ? FIGMA.partlyFrom(files) : kind === "unknown" ? "" : FIGMA.answeredFrom(files);
  return (
    <div className="flex flex-col gap-4" data-state={kind}>
      <Header caption={caption} kind={kind} />
      {kind === "unknown" ? <Notice tone="neutral" title={PROVISIONAL.unknownState} /> : null}
      <div className="flex flex-col gap-2">
        {lines.map((line, index) => (
          <p key={index} className="text-body break-words text-fg">
            <CitationText text={line} labels={labels} activeNumber={activeNumber} onSelect={onSelect} />
          </p>
        ))}
      </div>
      {kind === "partial" ? (
        <Notice tone="info" title={FIGMA.partialTitle} body={message.missing_terms.length ? PROVISIONAL.missing(message.missing_terms.slice(0, 5).join(", ")) : BACKEND_NOTICES.partial} />
      ) : null}
      {kind === "low_confidence" ? <Notice tone="warning" title={FIGMA.lowConfidenceTitle} body={BACKEND_NOTICES.low_confidence} /> : null}
      {message.citations.length ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="text-caption-strong text-fg-secondary">{FIGMA.sources}</span>
          <ul className="flex flex-wrap items-center gap-x-4 gap-y-1">
            {message.citations.map((c) => (
              <li key={c.number}>
                <button
                  type="button"
                  aria-pressed={activeNumber === c.number}
                  aria-label={labels.get(c.number)}
                  onClick={(event) => onSelect(c.number, event.currentTarget)}
                  className="flex min-h-11 items-center gap-1 rounded-md px-1 text-left hover:bg-subtle"
                >
                  <span
                    aria-hidden="true"
                    className={`inline-flex h-[22px] min-w-6 items-center justify-center rounded-sm border px-1 text-caption-strong ${activeNumber === c.number ? "border-accent bg-accent text-fg-on-accent" : "border-accent-subtle-border bg-accent-subtle text-accent-fg"}`}
                  >
                    [{c.number}]
                  </span>
                  <span className="text-caption break-all text-fg-secondary">{`${c.file_name} · ${c.citation_label}`}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

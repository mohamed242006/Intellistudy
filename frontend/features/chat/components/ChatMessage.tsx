"use client";

import { Notice } from "@/design-system/components/Notice";
import { SourceCard } from "@/design-system/components/SourceCard";
import { CitationText } from "@/design-system/compositions/CitationText";
import { BrandMark } from "@/design-system/compositions/Wordmark";
import { Icon } from "@/design-system/icons/Icon";
import { PROVISIONAL as SOURCE_COPY } from "@/features/sources/strings";
import type { MessageOut } from "@/lib/api/types";
import { followUps, isVagueReference, scopedQuestion } from "../clarify";
import { BACKEND_NOTICES, FIGMA, PROVISIONAL } from "../strings";

export type AnswerKind = "answered" | "partial" | "low_confidence" | "refused" | "unknown";

/** The backend's state, never upgraded or downgraded (gate GF1-18). Unknown future states claim nothing. */
export function answerKind(state: string): AnswerKind {
  return state === "answered" || state === "partial" || state === "low_confidence" || state === "refused" ? state : "unknown";
}

export function citedFileCount(message: Pick<MessageOut, "citations">): number {
  return new Set(message.citations.map((c) => c.document_id)).size;
}

/** Plain-text copy of an answer: the text as written (with its [n] markers) and the numbered sources. */
export function answerAsText(message: Pick<MessageOut, "text" | "citations">): string {
  const sources = message.citations.map((c) => `[${c.number}] ${c.file_name} · ${c.citation_label}`);
  return sources.length ? `${message.text.trim()}\n\n${FIGMA.sources}\n${sources.join("\n")}` : message.text.trim();
}

/** Assistant header (spec §4.23.1): the brand mark as avatar, "IntelliStudy", and the status caption. */
function Header({ caption, kind, children }: { caption: string; kind: AnswerKind | "loading"; children?: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-2" data-kind={kind}>
      <BrandMark size={24} />
      <span className="text-label text-fg">{FIGMA.assistant}</span>
      <span className="text-caption text-fg-secondary">{caption}</span>
      {children}
    </div>
  );
}

/** The question, as the reader wrote it (normalised by the backend). Right-aligned `accent/subtle` bubble (spec §4.23.1). */
export function UserBubble({ text }: { text: string }) {
  return (
    <div className="motion-enter-fast flex justify-end">
      <p className="max-w-[min(560px,85%)] min-w-0 rounded-lg bg-accent-subtle px-4 py-3 text-body break-words whitespace-pre-line text-fg">
        <span className="sr-only">{PROVISIONAL.you}: </span>
        {text}
      </p>
    </div>
  );
}

/** Loading (spec §4.23.1): "Working" with a typing indicator, three pulsing skeleton lines and the status row. */
export function PendingAnswer({ searching }: { searching: string }) {
  return (
    <div className="motion-enter-fast flex flex-col gap-4" aria-busy="true">
      <Header caption={FIGMA.working} kind="loading">
        <span aria-hidden="true" className="motion-dots inline-flex items-center gap-1 pl-1">
          <span className="size-1.5 rounded-full bg-fg-tertiary" />
          <span className="size-1.5 rounded-full bg-fg-tertiary" />
          <span className="size-1.5 rounded-full bg-fg-tertiary" />
        </span>
      </Header>
      <div aria-hidden="true" className="flex flex-col gap-3">
        <span className="motion-pulse h-3 w-full rounded-sm bg-subtle" />
        <span className="motion-pulse h-3 w-[92%] rounded-sm bg-subtle" />
        <span className="motion-pulse h-3 w-[64%] rounded-sm bg-subtle" />
      </div>
      <p className="flex items-center gap-2 text-body-sm text-fg-secondary">
        <Icon name="loader" size={16} />
        <span>{searching}</span>
      </p>
    </div>
  );
}

/** Suggestion chips: each one fills the composer with a question; nothing is sent until the reader sends it. */
function Suggestions({ label, items, onPick }: { label: string; items: { key: string; text: string; display: string }[]; onPick: (text: string) => void }) {
  if (!items.length) return null;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-caption-strong text-fg-secondary">{label}</p>
      <ul className="flex flex-wrap gap-2">
        {items.map((item) => (
          <li key={item.key} className="min-w-0">
            <button
              type="button"
              onClick={() => onPick(item.text)}
              className="flex min-h-11 max-w-full items-center gap-2 rounded-full border border-line-strong bg-surface px-3 py-1 text-left text-label text-fg hover:bg-subtle"
            >
              <Icon name="file" size={16} className="text-fg-secondary" />
              <span className="min-w-0 wrap-anywhere">{item.display}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export type ChatContext = {
  courseId: string;
  /** Ready files of the course (real data), offered as clarification choices. */
  files: ReadonlyArray<{ id: string; file_name: string }>;
  /** Puts a question in the composer and focuses it; it is not sent. */
  onSuggest: (text: string) => void;
  onCopy: (text: string) => void;
};

/**
 * One assistant answer (spec §4.23.1; gates GF1-14, GF1-15, GF1-18, GF1-20). Answer text, notices and sources are text.
 * Badges and the Sources row open only this message's citations. A refusal stays a refusal: the guidance below it
 * (clarification, follow-ups, closest material) only helps the reader ask again.
 */
export function AssistantMessage({ message, activeNumber, onSelect, context }: {
  message: MessageOut;
  activeNumber: number | null;
  onSelect: (number: number, trigger: HTMLButtonElement) => void;
  context?: ChatContext;
}) {
  const kind = answerKind(message.state);
  const labels = new Map(message.citations.map((c) => [c.number, SOURCE_COPY.sourceLabel(c.number, c.file_name, c.citation_label)]));
  const files = citedFileCount(message);
  const lines = message.text.split("\n").map((line) => line.trim()).filter(Boolean);

  if (kind === "refused") {
    const unavailable = message.refusal_reason === "llm_unavailable";
    const withheld = ["uncited_answer", "unsupported_claims", "scope_violation"].includes(message.refusal_reason ?? "");
    const nearest = unavailable ? [] : message.nearest.slice(0, 3);
    const vague = !unavailable && context ? isVagueReference(message.question, context.files.map((f) => f.file_name)) : false;
    const next = !unavailable && context ? followUps(nearest) : [];
    return (
      <div className="motion-enter-fast flex flex-col gap-4" data-state="refused">
        <Header caption={unavailable ? PROVISIONAL.unavailableCaption : FIGMA.notFound} kind="refused" />
        <div className="flex flex-col gap-3 rounded-lg border border-line bg-subtle p-4">
          <p className="flex items-start gap-2 text-title text-fg">
            <Icon name="info" size={20} className="mt-0.5 text-fg-secondary" />
            <span>{unavailable ? PROVISIONAL.unavailableTitle : withheld ? PROVISIONAL.withheldTitle : FIGMA.refusedTitle}</span>
          </p>
          <p className="text-body break-words whitespace-pre-line text-fg-secondary">{message.text}</p>
        </div>
        {vague && context ? (
          <div className="flex flex-col gap-3 rounded-lg border border-accent-subtle-border bg-accent-subtle p-4" data-clarify="">
            <p className="text-title text-fg">{PROVISIONAL.clarifyTitle}</p>
            <p className="text-body-sm text-fg-secondary">{PROVISIONAL.clarifyBody}</p>
            {context.files.length ? (
              <Suggestions
                label={PROVISIONAL.clarifyFiles}
                items={context.files.slice(0, 6).map((f) => ({ key: f.id, text: scopedQuestion(message.question, f.file_name), display: f.file_name }))}
                onPick={context.onSuggest}
              />
            ) : (
              <p className="text-body-sm text-fg-secondary">{PROVISIONAL.noReadyFiles}</p>
            )}
          </div>
        ) : null}
        {next.length && context ? (
          <Suggestions label={PROVISIONAL.tryAsking} items={next.map((text) => ({ key: text, text, display: text }))} onPick={context.onSuggest} />
        ) : null}
        {nearest.length ? (
          <div className="flex flex-col gap-2">
            <p className="text-caption-strong text-fg-secondary">{PROVISIONAL.closestMaterial}</p>
            <p className="text-caption text-fg-secondary">{PROVISIONAL.closestHint}</p>
            <div className="grid gap-3 md:grid-cols-2">
              {nearest.map((source, index) => (
                <SourceCard
                  key={`${source.document_id}-${index}`}
                  fileName={source.file_name}
                  location={source.citation_label}
                  passage={source.passage}
                  clamp
                  href={context ? `/courses/${encodeURIComponent(context.courseId)}?file=${encodeURIComponent(source.document_id)}` : undefined}
                  openLabel={PROVISIONAL.openFile}
                  moreLabel={PROVISIONAL.showMorePassage}
                  lessLabel={PROVISIONAL.showLessPassage}
                />
              ))}
            </div>
          </div>
        ) : null}
      </div>
    );
  }

  const caption = kind === "partial" ? FIGMA.partlyFrom(files) : kind === "unknown" ? "" : FIGMA.answeredFrom(files);
  return (
    <div className="motion-enter-fast flex min-w-0 flex-col gap-4" data-state={kind}>
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
        <div className="flex flex-col gap-2">
          <span className="text-caption-strong text-fg-secondary">{FIGMA.sources}</span>
          <ul className="flex flex-wrap items-center gap-2">
            {message.citations.map((c) => (
              <li key={c.number} className="min-w-0 max-w-full">
                <button
                  type="button"
                  aria-pressed={activeNumber === c.number}
                  aria-label={labels.get(c.number)}
                  onClick={(event) => onSelect(c.number, event.currentTarget)}
                  className={`flex min-h-11 max-w-full items-center gap-2 rounded-sm px-2 py-1 text-left hover:bg-accent-subtle ${activeNumber === c.number ? "bg-accent-subtle" : "bg-subtle"}`}
                >
                  <span
                    aria-hidden="true"
                    className={`inline-flex h-[22px] min-w-6 shrink-0 items-center justify-center rounded-sm border px-1 text-caption-strong ${activeNumber === c.number ? "border-accent bg-accent text-fg-on-accent" : "border-accent-subtle-border bg-accent-subtle text-accent-fg"}`}
                  >
                    [{c.number}]
                  </span>
                  <span className="min-w-0 text-caption wrap-anywhere text-fg-secondary">{`${c.file_name} · ${c.citation_label}`}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {context && kind !== "unknown" ? (
        <div className="flex">
          <button
            type="button"
            onClick={() => context.onCopy(answerAsText(message))}
            className="inline-flex min-h-11 items-center gap-2 rounded-md px-2 text-label text-accent-fg hover:bg-accent-subtle"
          >
            <Icon name="layers" size={16} />
            {PROVISIONAL.copyAnswer}
          </button>
        </div>
      ) : null}
    </div>
  );
}

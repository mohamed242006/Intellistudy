import type { ChangeEvent } from "react";

/**
 * AnswerOption (UI §7.19): H, padding 12/16, gap 12, radius 12, label `text/body`.
 * - Choice: a native radio inside its label (arrow keys, form semantics). Default `bg/surface` + 1 px `border/strong`;
 *   Hover `bg/subtle`; Selected `accent/subtle` fill + 2 px `accent/default` stroke (drawn inside); Focus 2 px ring;
 *   Disabled.
 * - Review: a static row. Correct `success/bg` + 2 px `success/solid` + the word "Correct"; Incorrect `danger/bg` +
 *   2 px `danger/solid` + the word "Incorrect". Verdicts are always words, never colour alone.
 */
export function AnswerChoice({ name, value, label, checked, disabled, onChange }: {
  name: string;
  value: string;
  label: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <label
      data-selected={checked || undefined}
      className={[
        "flex min-h-11 cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 focus-within:outline-2 focus-within:outline-focus-ring",
        checked ? "border-accent bg-accent-subtle shadow-[inset_0_0_0_1px_var(--color-accent)]" : "border-line-strong bg-surface hover:bg-subtle",
        disabled ? "cursor-not-allowed border-line bg-disabled-bg text-disabled-fg" : "",
      ].join(" ")}
    >
      <input type="radio" name={name} value={value} checked={checked} disabled={disabled} onChange={onChange} className="size-5 shrink-0 accent-[var(--color-accent)] focus-visible:outline-none" />
      <span className="min-w-0 flex-1 text-body break-words text-fg">{label}</span>
    </label>
  );
}

export type ReviewVerdict = "correct" | "incorrect" | "neutral";

const LOOK: Record<ReviewVerdict, string> = {
  correct: "border-success-solid bg-success-bg shadow-[inset_0_0_0_1px_var(--color-success-solid)]",
  incorrect: "border-danger-solid bg-danger-bg shadow-[inset_0_0_0_1px_var(--color-danger-solid)]",
  neutral: "border-line bg-surface",
};

export function AnswerReviewRow({ label, verdict, verdictText, note }: {
  label: string;
  verdict: ReviewVerdict;
  /** "Correct" / "Incorrect" (UI §7.19), shown as text. */
  verdictText?: string;
  /** For example "Your answer". */
  note?: string;
}) {
  return (
    <div data-verdict={verdict} className={`flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-4 py-3 ${LOOK[verdict]}`}>
      <span className="min-w-0 flex-1 text-body break-words text-fg">{label}</span>
      {note ? <span className="text-caption text-fg-secondary">{note}</span> : null}
      {verdictText ? <span className={`text-caption-strong ${verdict === "correct" ? "text-success-fg" : "text-danger-fg"}`}>{verdictText}</span> : null}
    </div>
  );
}

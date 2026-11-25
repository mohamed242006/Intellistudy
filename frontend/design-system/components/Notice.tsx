import { Icon } from "../icons/Icon";

/**
 * Notice (UI §7.15b): H, padding 16, gap 12, radius 12, 1 px border; leading icon + Title (`text/label`) + optional Body
 * (`text/body-sm`, secondary). Tones Info · Warning · Neutral. Not dismissible.
 */
export type NoticeTone = "info" | "warning" | "neutral";

const TONE: Record<NoticeTone, string> = {
  info: "border-accent-subtle-border bg-accent-subtle",
  warning: "border-warning-border bg-warning-bg",
  neutral: "border-line bg-subtle",
};

export function Notice({ tone, title, body }: { tone: NoticeTone; title: string; body?: string }) {
  return (
    <div data-tone={tone} className={`flex items-start gap-3 rounded-lg border p-4 ${TONE[tone]}`}>
      {tone === "neutral" ? null : <Icon name={tone === "info" ? "info" : "alert"} size={20} />}
      <div className="flex flex-col gap-1">
        <p className="text-label text-fg">{title}</p>
        {body ? <p className="text-body-sm text-fg-secondary">{body}</p> : null}
      </div>
    </div>
  );
}

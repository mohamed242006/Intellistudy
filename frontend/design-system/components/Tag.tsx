/** Tag (UI §7.5): status label, never a button. Height 24, padding 0/8, radius 4, `text/caption-strong`, no border. */
export type TagTone = "neutral" | "accent" | "success" | "warning" | "danger";

const TONE: Record<TagTone, string> = {
  neutral: "bg-subtle text-fg-secondary",
  accent: "bg-accent-subtle text-accent-fg",
  success: "bg-success-bg text-success-fg",
  warning: "bg-warning-bg text-warning-fg",
  danger: "bg-danger-bg text-danger-fg",
};

export function Tag({ tone, children }: { tone: TagTone; children: string }) {
  return (
    <span data-tone={tone} className={`inline-flex h-6 shrink-0 items-center rounded-sm px-2 text-caption-strong whitespace-nowrap ${TONE[tone]}`}>
      {children}
    </span>
  );
}

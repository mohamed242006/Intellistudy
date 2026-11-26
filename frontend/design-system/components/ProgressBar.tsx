/**
 * ProgressBar (UI §7.7): track 8 high, radius 999, `bg/subtle`; the fill width is the real value (the Figma variants
 * are three fixed widths, UI §7.7 caveat). Status Active · Success · Error recolours the fill.
 */
export type ProgressStatus = "active" | "success" | "error";

const FILL: Record<ProgressStatus, string> = { active: "bg-accent", success: "bg-success-solid", error: "bg-danger-solid" };

export function ProgressBar({ value, label, status = "active", className = "" }: {
  /** 0-100; clamped. */
  value: number;
  /** Accessible name, for example "Uploading lecture.pdf". */
  label: string;
  status?: ProgressStatus;
  className?: string;
}) {
  const clamped = Math.min(100, Math.max(0, Math.round(Number.isFinite(value) ? value : 0)));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
      aria-valuetext={`${clamped}%`}
      className={`h-2 w-80 max-w-full overflow-hidden rounded-full bg-subtle ${className}`}
    >
      <div data-status={status} className={`motion-progress h-full rounded-full ${FILL[status]}`} style={{ width: `${clamped}%` }} />
    </div>
  );
}

import type { ReactNode } from "react";
import { Icon } from "../icons/Icon";
import { ProgressBar } from "./ProgressBar";
import { Tag, type TagTone } from "./Tag";

/**
 * FileUploadRow (UI §7.16): H, padding 12, gap 12, radius 12, 1 px border, items centred. 40×40 icon tile (radius 8,
 * file icon 20) → details (name `text/label` + Tag; status `text/body-sm`; ProgressBar while uploading) → action.
 * Border `danger/border` for Failed / Not supported / Empty. "Waiting" is a client-only status (provisional).
 * Status is always text (Tag + sentence), never colour alone.
 */
export type FileRowStatus = "waiting" | "uploading" | "extracting" | "indexed" | "failed" | "unsupported" | "empty";

const LOOK: Record<FileRowStatus, { tile: string; text: string; tag: TagTone; danger: boolean }> = {
  waiting: { tile: "bg-subtle", text: "text-fg-secondary", tag: "neutral", danger: false },
  uploading: { tile: "bg-accent-subtle", text: "text-accent-fg", tag: "accent", danger: false },
  extracting: { tile: "bg-accent-subtle", text: "text-accent-fg", tag: "accent", danger: false },
  indexed: { tile: "bg-success-bg", text: "text-success-fg", tag: "success", danger: false },
  failed: { tile: "bg-danger-bg", text: "text-danger-fg", tag: "danger", danger: true },
  unsupported: { tile: "bg-danger-bg", text: "text-danger-fg", tag: "danger", danger: true },
  empty: { tile: "bg-danger-bg", text: "text-danger-fg", tag: "danger", danger: true },
};

export function FileUploadRow({ name, status, tag, detail, progress, actions }: {
  name: string;
  status: FileRowStatus;
  tag: string;
  detail: string;
  /** 0-100 while uploading. */
  progress?: number;
  actions?: ReactNode;
}) {
  const look = LOOK[status];
  return (
    <div
      data-status={status}
      className={`flex items-center gap-3 rounded-lg border bg-surface p-3 hover:bg-subtle max-sm:flex-wrap ${look.danger ? "border-danger-border" : "border-line"}`}
    >
      <span className={`flex size-10 shrink-0 items-center justify-center rounded-md ${look.tile}`}>
        <Icon name="file" size={20} />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="min-w-0 text-label wrap-anywhere text-fg">{name}</span>
          <Tag tone={look.tag}>{tag}</Tag>
        </div>
        <p className={`text-body-sm break-words ${look.text}`}>{detail}</p>
        {status === "uploading" && progress !== undefined ? <ProgressBar value={progress} label={`Uploading ${name}`} /> : null}
      </div>
      {actions ? <div className="flex shrink-0 gap-2 max-sm:w-full max-sm:justify-end">{actions}</div> : null}
    </div>
  );
}

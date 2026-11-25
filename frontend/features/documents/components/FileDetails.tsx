"use client";

import { Button } from "@/design-system/components/Button";
import { Tag, type TagTone } from "@/design-system/components/Tag";
import type { DocumentOut } from "@/lib/api/types";
import { relativeTime } from "@/lib/format/format";
import { documentView, fileTypeLabel, sizeLabel } from "../status";
import { FIGMA, PROVISIONAL } from "../strings";

const TAG_TONE: Record<string, TagTone> = { extracting: "accent", indexed: "success", failed: "danger", unsupported: "danger", empty: "danger" };

/**
 * Selected-file details (UI §8.3 right column; gate GF0B-10). Backend fields only: type, size, pages or slides, upload
 * and index times. "Open summary", "Ask about this file", "Generate quiz" and topic chips belong to F1/F2 and are
 * not rendered. Actions: Download, Retry (Failed only), Delete file.
 */
export function FileDetails({ document, now, onDownload, downloading, onRetry, retrying, onDelete }: {
  document: DocumentOut;
  now: Date;
  onDownload: () => void;
  downloading: boolean;
  onRetry: () => void;
  retrying: boolean;
  onDelete: () => void;
}) {
  const view = documentView(document, now);
  const rows: [string, string][] = [[PROVISIONAL.type, fileTypeLabel(document.file_type)], [FIGMA.size, sizeLabel(document.size_bytes)]];
  if (document.page_count !== null) rows.push([document.file_type === "pptx" ? PROVISIONAL.slides : FIGMA.pages, String(document.page_count)]);
  rows.push([PROVISIONAL.uploaded, relativeTime(document.created_at, now)]);
  if (document.status === "ready" && document.ready_at) rows.push([FIGMA.indexedAt, relativeTime(document.ready_at, now)]);
  return (
    <section aria-labelledby="selected-file-name" className="flex flex-col gap-4">
      {/* text/secondary, not tertiary: tertiary is below 4.5:1 on the canvas background (same decision as F0-A) */}
      <p className="text-caption-strong text-fg-secondary">{FIGMA.selectedFile}</p>
      <h2 id="selected-file-name" className="text-h3 break-all text-fg">
        {document.file_name}
      </h2>
      <div>
        <Tag tone={TAG_TONE[view.status] ?? "neutral"}>{view.tag}</Tag>
      </div>
      <p className={`text-body-sm ${view.status === "indexed" || view.status === "extracting" ? "text-fg-secondary" : "text-danger-fg"}`}>{view.detail}</p>
      <dl className="flex flex-col">
        {rows.map(([term, value]) => (
          <div key={term} className="flex justify-between gap-4 border-b border-line py-3 text-body-sm">
            <dt className="text-fg-secondary">{term}</dt>
            <dd className="text-right text-fg">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex flex-col gap-3">
        <Button variant="secondary" fullWidth loading={downloading} onClick={onDownload}>
          {PROVISIONAL.download}
        </Button>
        {view.canRetry ? (
          <Button variant="secondary" fullWidth loading={retrying} onClick={onRetry}>
            {FIGMA.retry}
          </Button>
        ) : null}
        <Button variant="secondary" fullWidth onClick={onDelete}>
          {PROVISIONAL.deleteFile}
        </Button>
      </div>
    </section>
  );
}

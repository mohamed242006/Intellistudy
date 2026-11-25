/**
 * Backend document status → UI status (gate GF0B-18; plan section 7). Verified values: backend/app/db/models.py
 * DocumentStatus and services/documents.py REASONS. The backend exposes no OCR signal, so no OCR status exists here.
 */
import type { FileRowStatus } from "@/design-system/components/FileUploadRow";
import type { DocumentOut } from "@/lib/api/types";
import { formatBytes, relativeTime } from "@/lib/format/format";
import { BACKEND_REASONS, FIGMA, PROVISIONAL } from "./strings";

export const IN_PROGRESS_STATUSES = ["queued", "validating", "extracting", "chunking", "embedding", "indexing"] as const;
export const TERMINAL_STATUSES = ["ready", "failed"] as const;

/** Codes whose failure means "nothing to index" (UI Empty). */
export const EMPTY_CODES = new Set(["no_text", "empty_file"]);
/** Codes whose failure means the file kind is refused (UI Not supported). */
export const UNSUPPORTED_CODES = new Set(["unsupported_type", "type_mismatch", "macro_document"]);

export function isInProgress(status: string): boolean {
  return (IN_PROGRESS_STATUSES as readonly string[]).includes(status);
}

export function reasonText(code: string | null | undefined): string {
  if (code === "no_text") return FIGMA.emptyDetail;
  if (code === "unsupported_type") return FIGMA.notSupportedDetail;
  return BACKEND_REASONS[code ?? ""] ?? BACKEND_REASONS.internal_error!;
}

export type DocumentView = { status: Exclude<FileRowStatus, "waiting" | "uploading">; tag: string; detail: string; canRetry: boolean };

export function documentView(doc: Pick<DocumentOut, "status" | "error_code" | "page_count" | "file_type" | "ready_at">, now: Date): DocumentView {
  if (isInProgress(doc.status)) return { status: "extracting", tag: FIGMA.extracting, detail: FIGMA.extractingDetail, canRetry: false };
  if (doc.status === "ready") {
    const unit = doc.file_type === "pptx" ? "slide" : "page";
    const when = relativeTime(doc.ready_at, now);
    const count = doc.page_count === null ? null : `${doc.page_count} ${doc.page_count === 1 ? unit : `${unit}s`}`;
    const detail = [count, when ? `indexed ${when}` : FIGMA.indexed].filter(Boolean).join(" · ");
    return { status: "indexed", tag: FIGMA.indexed, detail, canRetry: false };
  }
  if (doc.status === "failed") {
    const code = doc.error_code ?? "internal_error";
    if (EMPTY_CODES.has(code)) return { status: "empty", tag: FIGMA.empty, detail: reasonText(code), canRetry: false };
    if (UNSUPPORTED_CODES.has(code)) return { status: "unsupported", tag: FIGMA.notSupported, detail: reasonText(code), canRetry: false };
    return { status: "failed", tag: FIGMA.failed, detail: reasonText(code), canRetry: true };
  }
  // An unknown future status is shown as a failure without actions and does not keep polling alive.
  return { status: "failed", tag: FIGMA.failed, detail: BACKEND_REASONS.internal_error!, canRetry: false };
}

export type CourseFileSummary = { total: number; indexed: number; processing: number; attention: number; complete: boolean };

export function summarise(docs: readonly Pick<DocumentOut, "status">[], complete: boolean): CourseFileSummary {
  let indexed = 0;
  let processing = 0;
  for (const doc of docs) {
    if (doc.status === "ready") indexed += 1;
    else if (isInProgress(doc.status)) processing += 1;
  }
  return { total: docs.length, indexed, processing, attention: docs.length - indexed - processing, complete };
}

export function fileTypeLabel(fileType: string): string {
  return ({ pdf: "PDF", docx: "Word (.docx)", pptx: "PowerPoint (.pptx)" } as Record<string, string>)[fileType] ?? fileType.toUpperCase();
}

export function sizeLabel(bytes: number): string {
  return formatBytes(bytes);
}

export { PROVISIONAL };

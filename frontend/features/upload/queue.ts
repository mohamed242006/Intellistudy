/**
 * Upload queue state (gate GF0B-14..17), as a pure reducer. One row per selected file, newest first (UI §18 D-13).
 * Selecting files only stages them (`selected`); "Add this file / Add these files" submits every staged file at once
 * (`submit` → `pending`), and the scheduler uploads pending rows one at a time. A row leaves the queue when the backend
 * accepts its file: from then on the course's document list (polled) shows it. `batch` follows the last submission so
 * the page can tell success, partial failure and failure apart without guessing.
 */
import type { FileRowStatus } from "@/design-system/components/FileUploadRow";
import { ApiError } from "@/lib/api/errors";
import { reasonText } from "@/features/documents/status";
import { FIGMA, PROVISIONAL } from "@/features/documents/strings";
import { clientProblem, selectionKey, type ClientProblem } from "./validation";

export type RowProblem = { status: Extract<FileRowStatus, "failed" | "unsupported" | "empty">; message: string; retryable: boolean };

export type UploadItem = {
  id: string;
  key: string;
  file: File;
  /** selected: staged, not sent until submitted; pending: submitted, waiting for its turn. */
  phase: "selected" | "pending" | "uploading" | "problem";
  /** 0-100 while uploading. */
  progress: number;
  problem: RowProblem | null;
};

/** The last submission: which rows it contained and how many the backend accepted. */
export type Batch = { ids: string[]; accepted: number };

export type QueueState = { items: UploadItem[]; batch: Batch | null };

export type QueueAction =
  | { type: "add"; files: File[]; makeId: () => string }
  | { type: "submit" }
  /** The content check refused a file that has not started uploading (a running transfer is never interrupted). */
  | { type: "refused"; id: string; problem: RowProblem }
  | { type: "start"; id: string }
  | { type: "progress"; id: string; percent: number }
  | { type: "accepted"; id: string }
  | { type: "requeue"; id: string }
  | { type: "problem"; id: string; problem: RowProblem }
  | { type: "retry"; id: string }
  | { type: "remove"; id: string };

export const initialQueue: QueueState = { items: [], batch: null };

export function problemForClient(problem: ClientProblem): RowProblem {
  if (problem === "unsupported_type") return { status: "unsupported", message: FIGMA.notSupportedDetail, retryable: false };
  if (problem === "type_mismatch") return { status: "unsupported", message: PROVISIONAL.typeMismatch, retryable: false };
  if (problem === "empty_file") return { status: "empty", message: reasonText("empty_file"), retryable: false };
  return { status: "failed", message: PROVISIONAL.tooLarge, retryable: false };
}

function waitText(seconds: number | null): string {
  return seconds === null ? PROVISIONAL.inAWhile : PROVISIONAL.inSeconds(seconds);
}

/** The row outcome for a failed upload request. `queue_full` is handled by the scheduler before this is used. */
export function problemForError(error: unknown): RowProblem {
  if (!(error instanceof ApiError)) return { status: "failed", message: PROVISIONAL.uploadFailed, retryable: true };
  if (error.code === "upload_rejected") {
    const reason = error.files[0]?.reason ?? "unsupported_type";
    if (reason === "empty_file") return { status: "empty", message: reasonText(reason), retryable: false };
    return { status: "unsupported", message: reasonText(reason), retryable: false };
  }
  if (error.code === "file_too_large") return { status: "failed", message: PROVISIONAL.tooLarge, retryable: false };
  if (error.code === "malformed_upload") return { status: "failed", message: PROVISIONAL.uploadIncomplete, retryable: true };
  if (error.code === "quota_exceeded") return { status: "failed", message: PROVISIONAL.quotaExceeded, retryable: false };
  if (error.code === "queue_full") return { status: "failed", message: PROVISIONAL.queueFull, retryable: true };
  if (error.code === "rate_limited") return { status: "failed", message: PROVISIONAL.rateLimited(waitText(error.retryAfterSeconds)), retryable: true };
  if (error.kind === "network") return { status: "failed", message: PROVISIONAL.networkFailed, retryable: true };
  if (error.kind === "not_found") return { status: "failed", message: PROVISIONAL.courseGone, retryable: false };
  if (error.kind === "session_expired" || error.kind === "unauthorized") return { status: "failed", message: PROVISIONAL.sessionExpired, retryable: false };
  return { status: "failed", message: PROVISIONAL.uploadFailed, retryable: true };
}

function update(state: QueueState, id: string, fn: (item: UploadItem) => UploadItem): QueueState {
  return { ...state, items: state.items.map((item) => (item.id === id ? fn(item) : item)) };
}

export function queueReducer(state: QueueState, action: QueueAction): QueueState {
  switch (action.type) {
    case "add": {
      const queued = new Set(state.items.filter((item) => item.phase !== "problem").map((item) => item.key));
      const added: UploadItem[] = [];
      for (const file of action.files) {
        const key = selectionKey(file);
        if (queued.has(key)) continue; // the same file chosen twice while still queued (GF0B-14)
        queued.add(key);
        const problem = clientProblem(file);
        added.push({
          id: action.makeId(),
          key,
          file,
          phase: problem ? "problem" : "selected",
          progress: 0,
          problem: problem ? problemForClient(problem) : null,
        });
      }
      return { ...state, items: [...added.reverse(), ...state.items] };
    }
    case "submit": {
      const staged = state.items.filter((item) => item.phase === "selected").map((item) => item.id);
      if (staged.length === 0) return state;
      const open = state.batch && batchProgress(state).active > 0 ? state.batch : null; // still uploading: extend it
      return {
        items: state.items.map((item) => (item.phase === "selected" ? { ...item, phase: "pending" } : item)),
        batch: open ? { ids: [...open.ids, ...staged], accepted: open.accepted } : { ids: staged, accepted: 0 },
      };
    }
    case "start":
      return update(state, action.id, (item) => ({ ...item, phase: "uploading", progress: 0, problem: null }));
    case "progress":
      return update(state, action.id, (item) => (item.phase === "uploading" ? { ...item, progress: action.percent } : item));
    case "requeue":
      return update(state, action.id, (item) => ({ ...item, phase: "pending", progress: 0 }));
    case "problem":
      return update(state, action.id, (item) => ({ ...item, phase: "problem", progress: 0, problem: action.problem }));
    case "refused":
      return update(state, action.id, (item) =>
        item.phase === "selected" || item.phase === "pending" ? { ...item, phase: "problem", progress: 0, problem: action.problem } : item,
      );
    case "retry":
      return update(state, action.id, (item) => (item.problem?.retryable ? { ...item, phase: "pending", problem: null } : item));
    case "accepted":
      return {
        items: state.items.filter((item) => item.id !== action.id),
        batch: state.batch && state.batch.ids.includes(action.id) ? { ...state.batch, accepted: state.batch.accepted + 1 } : state.batch,
      };
    case "remove":
      return {
        items: state.items.filter((item) => item.id !== action.id),
        batch: state.batch ? { ...state.batch, ids: state.batch.ids.filter((id) => id !== action.id) } : null,
      };
  }
}

/** The next file to send: the oldest pending row (rows are newest first). */
export function nextPending(state: QueueState): UploadItem | undefined {
  for (let i = state.items.length - 1; i >= 0; i -= 1) {
    if (state.items[i]!.phase === "pending") return state.items[i];
  }
  return undefined;
}

/** Where the last submission stands: rows still on their way, rows the backend refused, rows it accepted. */
export function batchProgress(state: QueueState): { active: number; failed: number; accepted: number; done: boolean } {
  if (!state.batch) return { active: 0, failed: 0, accepted: 0, done: false };
  const ids = new Set(state.batch.ids);
  let active = 0;
  let failed = 0;
  for (const item of state.items) {
    if (!ids.has(item.id)) continue;
    if (item.phase === "pending" || item.phase === "uploading") active += 1;
    else if (item.phase === "problem") failed += 1;
  }
  return { active, failed, accepted: state.batch.accepted, done: active === 0 && state.batch.accepted + failed > 0 };
}

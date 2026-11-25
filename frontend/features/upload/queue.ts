/**
 * Upload queue state (gate GF0B-14..17), as a pure reducer. One row per selected file, newest first (UI §18 D-13).
 * A row leaves the queue when the backend accepts its file: from then on the course's document list (polled) shows it.
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
  phase: "pending" | "uploading" | "problem";
  /** 0-100 while uploading. */
  progress: number;
  problem: RowProblem | null;
};

export type QueueState = { items: UploadItem[] };

export type QueueAction =
  | { type: "add"; files: File[]; makeId: () => string }
  | { type: "start"; id: string }
  | { type: "progress"; id: string; percent: number }
  | { type: "accepted"; id: string }
  | { type: "requeue"; id: string }
  | { type: "problem"; id: string; problem: RowProblem }
  | { type: "retry"; id: string }
  | { type: "remove"; id: string };

export const initialQueue: QueueState = { items: [] };

export function problemForClient(problem: ClientProblem): RowProblem {
  if (problem === "unsupported_type") return { status: "unsupported", message: FIGMA.notSupportedDetail, retryable: false };
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
  if (error.code === "quota_exceeded") return { status: "failed", message: PROVISIONAL.quotaExceeded, retryable: false };
  if (error.code === "queue_full") return { status: "failed", message: PROVISIONAL.queueFull, retryable: true };
  if (error.code === "rate_limited") return { status: "failed", message: PROVISIONAL.rateLimited(waitText(error.retryAfterSeconds)), retryable: true };
  if (error.kind === "network") return { status: "failed", message: PROVISIONAL.networkFailed, retryable: true };
  if (error.kind === "not_found") return { status: "failed", message: PROVISIONAL.courseGone, retryable: false };
  if (error.kind === "session_expired" || error.kind === "unauthorized") return { status: "failed", message: PROVISIONAL.sessionExpired, retryable: false };
  return { status: "failed", message: PROVISIONAL.uploadFailed, retryable: true };
}

function update(state: QueueState, id: string, fn: (item: UploadItem) => UploadItem): QueueState {
  return { items: state.items.map((item) => (item.id === id ? fn(item) : item)) };
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
          phase: problem ? "problem" : "pending",
          progress: 0,
          problem: problem ? problemForClient(problem) : null,
        });
      }
      return { items: [...added.reverse(), ...state.items] };
    }
    case "start":
      return update(state, action.id, (item) => ({ ...item, phase: "uploading", progress: 0, problem: null }));
    case "progress":
      return update(state, action.id, (item) => (item.phase === "uploading" ? { ...item, progress: action.percent } : item));
    case "requeue":
      return update(state, action.id, (item) => ({ ...item, phase: "pending", progress: 0 }));
    case "problem":
      return update(state, action.id, (item) => ({ ...item, phase: "problem", progress: 0, problem: action.problem }));
    case "retry":
      return update(state, action.id, (item) => (item.problem?.retryable ? { ...item, phase: "pending", problem: null } : item));
    case "accepted":
    case "remove":
      return { items: state.items.filter((item) => item.id !== action.id) };
  }
}

/** The next file to send: the oldest pending row (rows are newest first). */
export function nextPending(state: QueueState): UploadItem | undefined {
  for (let i = state.items.length - 1; i >= 0; i -= 1) {
    if (state.items[i]!.phase === "pending") return state.items[i];
  }
  return undefined;
}

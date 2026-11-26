/**
 * Document selection for Summary and Quiz (one model, used by DocumentPicker). Pure functions over the course's real
 * documents: only `ready` files can be selected; ids that disappear or stop being ready are dropped and reported, so a
 * request never carries a stale id and the reader is told why their selection changed.
 */
import type { DocumentOut } from "@/lib/api/types";

/** The same ceiling as the backend (MAX_QUIZ_DOCUMENTS and MAX_SUMMARY_DOCUMENTS in services/generation.py). */
export const MAX_SELECTED_DOCUMENTS = 20;

export type Selectable = Pick<DocumentOut, "id" | "status">;

export function readyIds(documents: readonly Selectable[]): string[] {
  return documents.filter((d) => d.status === "ready").map((d) => d.id);
}

/** Keeps the order the reader chose, drops ids that are no longer ready (or gone). */
export function prune(selected: readonly string[], documents: readonly Selectable[]): { kept: string[]; dropped: string[] } {
  const ready = new Set(readyIds(documents));
  const kept: string[] = [];
  const dropped: string[] = [];
  for (const id of selected) (ready.has(id) && !kept.includes(id) ? kept : dropped).push(id);
  return { kept, dropped };
}

export function toggle(selected: readonly string[], id: string, on: boolean, documents: readonly Selectable[]): string[] {
  if (!on) return selected.filter((s) => s !== id);
  if (selected.includes(id) || !readyIds(documents).includes(id)) return [...selected];
  return [...selected, id];
}

/** Every ready file, in course order (never a non-ready one). */
export function selectAll(documents: readonly Selectable[]): string[] {
  return readyIds(documents);
}

export type AllState = "none" | "some" | "all";

export function allState(selected: readonly string[], documents: readonly Selectable[]): AllState {
  const ready = readyIds(documents);
  const count = ready.filter((id) => selected.includes(id)).length;
  if (count === 0) return "none";
  return count === ready.length ? "all" : "some";
}

export function selectedCountText(count: number): string {
  return count === 1 ? "1 file selected" : `${count} files selected`;
}

/** "PDF", "DOCX", "PPTX" from the stored type, else from the name. */
export function fileKind(doc: Pick<DocumentOut, "file_type" | "file_name">): string {
  const raw = (doc.file_type || doc.file_name.split(".").pop() || "").toLowerCase();
  return raw === "pdf" || raw === "docx" || raw === "pptx" ? raw.toUpperCase() : raw.toUpperCase().slice(0, 5);
}

/** Splits a file name into its stem and extension so the stem can be truncated while the extension stays visible. */
export function splitName(name: string): { stem: string; ext: string } {
  const dot = name.lastIndexOf(".");
  if (dot <= 0 || dot === name.length - 1 || name.length - dot > 6) return { stem: name, ext: "" };
  return { stem: name.slice(0, dot), ext: name.slice(dot) };
}

/** Copy of the selection step and its actions (dynamic counts, never "1 files"). */
export const SELECTION_COPY = {
  files: (n: number) => (n === 1 ? "1 file" : `${n} files`),
  createSummary: (n: number) => `Create summary from ${n === 1 ? "1 file" : `${n} files`}`,
  createQuiz: (n: number) => `Create quiz from ${n === 1 ? "1 file" : `${n} files`}`,
  creatingSummary: "Creating summary…",
  creatingQuiz: "Creating quiz…",
  summaryHint: "Select at least one ready file to create a summary.",
  quizHint: "Select at least one ready file to create a quiz.",
  dropped: (n: number) =>
    n === 1 ? "1 selected file is no longer ready, so it was removed from your selection." : `${n} selected files are no longer ready, so they were removed from your selection.`,
} as const;

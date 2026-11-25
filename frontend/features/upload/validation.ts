/**
 * Client-side upload checks (gate GF0B-14). They only spare the user a pointless transfer: the backend repeats every
 * check by content (extension and magic bytes, then the sandbox), and its answer is authoritative.
 * Values verified in backend/app/core/config.py (max_upload_bytes) and services/storage.py (ALLOWED_EXTENSIONS).
 */

export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
export const ALLOWED_EXTENSIONS = ["pdf", "docx", "pptx"] as const;
/** For the file chooser only (a hint to the OS dialog, not a check). */
export const ACCEPT_ATTRIBUTE = [
  ".pdf",
  ".docx",
  ".pptx",
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation",
].join(",");

export type ClientProblem = "unsupported_type" | "empty_file" | "file_too_large";

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
}

export function clientProblem(file: Pick<File, "name" | "size">): ClientProblem | null {
  if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(extensionOf(file.name))) return "unsupported_type";
  if (file.size === 0) return "empty_file";
  if (file.size > MAX_UPLOAD_BYTES) return "file_too_large";
  return null;
}

/** Identity of a selected file, to ignore the same file chosen twice while it is still queued. */
export function selectionKey(file: Pick<File, "name" | "size" | "lastModified">): string {
  return `${file.name}\u0000${file.size}\u0000${file.lastModified}`;
}

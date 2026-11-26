/**
 * Client-side upload checks (gate GF0B-14). They only spare the user a pointless transfer: the backend repeats every
 * check by content (extension and magic bytes, then the sandbox), and its answer is authoritative.
 * Values verified in backend/app/core/config.py (max_upload_bytes) and services/storage.py (ALLOWED_EXTENSIONS).
 */

import { MAX_UPLOAD_BYTES } from "./limits";

export { MAX_UPLOAD_BYTES } from "./limits";
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

export type ClientProblem = "unsupported_type" | "type_mismatch" | "empty_file" | "file_too_large";

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

/** MIME types a browser may report for an allowed file. Many systems report "" or a generic type for Office files. */
const BROWSER_TYPES: Readonly<Record<string, readonly string[]>> = {
  pdf: ["application/pdf", "application/x-pdf"],
  docx: ["application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip", "application/x-zip-compressed"],
  pptx: ["application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/zip", "application/x-zip-compressed"],
};
const GENERIC_TYPES = ["", "application/octet-stream", "binary/octet-stream"];

/** The file's first bytes: PDF starts with "%PDF-", DOCX and PPTX are ZIP containers ("PK\x03\x04"). */
const MAGIC: Readonly<Record<string, readonly number[]>> = {
  pdf: [0x25, 0x50, 0x44, 0x46, 0x2d],
  docx: [0x50, 0x4b, 0x03, 0x04],
  pptx: [0x50, 0x4b, 0x03, 0x04],
};

/**
 * Content check before the transfer (runs after clientProblem passed): the browser-reported type, when specific, and the
 * file signature must match the extension. A renamed video or image is refused without sending it. The backend repeats
 * the check (and much more) by content; a file that cannot be read here is left to the backend.
 */
export async function contentProblem(file: Pick<File, "name" | "type" | "slice">): Promise<ClientProblem | null> {
  const ext = extensionOf(file.name);
  const reported = (file.type || "").toLowerCase();
  if (!GENERIC_TYPES.includes(reported) && !(BROWSER_TYPES[ext] ?? []).includes(reported)) return "type_mismatch";
  const magic = MAGIC[ext];
  if (!magic) return "unsupported_type";
  let head: Uint8Array;
  try {
    head = await readHead(file.slice(0, magic.length));
  } catch {
    return null; // unreadable here (permissions, a file moved meanwhile): the backend decides
  }
  return magic.every((byte, i) => head[i] === byte) ? null : "type_mismatch";
}

function readHead(blob: Blob): Promise<Uint8Array> {
  if (typeof blob.arrayBuffer === "function") return blob.arrayBuffer().then((buffer) => new Uint8Array(buffer));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(blob);
  });
}

/** Identity of a selected file, to ignore the same file chosen twice while it is still queued. */
export function selectionKey(file: Pick<File, "name" | "size" | "lastModified">): string {
  return `${file.name}\u0000${file.size}\u0000${file.lastModified}`;
}

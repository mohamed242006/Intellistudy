/**
 * Upload size limits, shared by the client-side checks and next.config.ts (no imports, so the config can load it).
 *
 * MAX_UPLOAD_BYTES mirrors the backend's per-file limit, backend/app/core/config.py `max_upload_bytes` (UPL-02, approved
 * 100 MB). The backend is authoritative and answers 413 `file_too_large` above it.
 *
 * PROXY_BODY_LIMIT_BYTES is the request-body limit of the Next.js server that proxies /api/v1/* to the backend (the
 * rewrite in next.config.ts). Next.js 15 copies every proxied body through a clone that stops after
 * `experimental.middlewareClientMaxBodySize` (default 10 MB) and forwards only the first part, so a larger upload reached
 * the backend cut off and was refused as `malformed_upload`. The frontend sends one file per request, so the limit is
 * one file plus room for the multipart framing (the backend allows the same 1 MiB of framing in api/v1/documents.py).
 */
export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024;
export const MULTIPART_HEADROOM_BYTES = 1024 * 1024;
export const PROXY_BODY_LIMIT_BYTES = MAX_UPLOAD_BYTES + MULTIPART_HEADROOM_BYTES;

/** "100 MB", for copy. Binary megabytes, as the backend counts them. */
export const MAX_UPLOAD_LABEL = `${MAX_UPLOAD_BYTES / (1024 * 1024)} MB`;

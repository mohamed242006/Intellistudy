/**
 * Upload of one file per request with XMLHttpRequest, for per-file progress (gate GF0B-15). `fetch` cannot report
 * upload progress, so this is the one transport outside apiRequest. It follows the same rules:
 * - `Authorization: Bearer` from memory, no cookies (`withCredentials` false), nothing logged;
 * - a 401 triggers one coordinated refresh and one retry; a second failure ends the session (GF0B-24);
 * - error bodies become typed ApiErrors through the same parser as every other call.
 * The backend validates each request all-or-nothing, so one file per request keeps outcomes independent.
 */

import { refreshSession } from "@/lib/auth/refresh";
import { tokenStore } from "@/lib/auth/token-store";
import { API_BASE, expireSession } from "./client";
import { ApiError, apiErrorFromBody, networkError, sessionExpiredError } from "./errors";
import type { UploadResponse } from "./types";

export type UploadProgress = { loaded: number; total: number };

/** Field name required by the backend's multipart parser (backend/app/services/uploads.py). */
export const UPLOAD_FIELD = "files";

export class UploadAbortedError extends Error {
  constructor() {
    super("upload aborted");
    this.name = "UploadAbortedError";
  }
}

type Attempt = { status: number; body: unknown; retryAfter: string | null };

function sendOnce(path: string, file: File, onProgress: (p: UploadProgress) => void, signal?: AbortSignal): Promise<Attempt> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new UploadAbortedError());
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`);
    xhr.withCredentials = false;
    xhr.responseType = "text";
    xhr.setRequestHeader("Accept", "application/json");
    const token = tokenStore.get();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    const abort = () => xhr.abort();
    signal?.addEventListener("abort", abort, { once: true });
    const done = () => signal?.removeEventListener("abort", abort);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress({ loaded: event.loaded, total: event.total });
    };
    xhr.onload = () => {
      done();
      let body: unknown = null;
      try {
        body = xhr.responseText ? JSON.parse(xhr.responseText) : null;
      } catch {
        body = null;
      }
      resolve({ status: xhr.status, body, retryAfter: xhr.getResponseHeader("Retry-After") });
    };
    xhr.onerror = () => {
      done();
      reject(networkError());
    };
    xhr.onabort = () => {
      done();
      reject(new UploadAbortedError());
    };

    const form = new FormData();
    form.append(UPLOAD_FIELD, file, file.name);
    xhr.send(form);
  });
}

/** Upload one file to a course. Resolves with the backend's 202 body; rejects with ApiError or UploadAbortedError. */
export async function uploadFile(
  courseId: string,
  file: File,
  onProgress: (progress: UploadProgress) => void,
  signal?: AbortSignal,
): Promise<UploadResponse> {
  const path = `/courses/${encodeURIComponent(courseId)}/documents`;
  let attempt = await sendOnce(path, file, onProgress, signal);
  if (attempt.status === 401) {
    const refreshed = await refreshSession();
    if (!refreshed) {
      expireSession();
      throw sessionExpiredError();
    }
    onProgress({ loaded: 0, total: file.size });
    attempt = await sendOnce(path, file, onProgress, signal);
    if (attempt.status === 401) {
      expireSession();
      throw sessionExpiredError();
    }
  }
  if (attempt.status >= 200 && attempt.status < 300) {
    const body = attempt.body as UploadResponse | null;
    if (!body || !Array.isArray(body.documents)) throw new ApiError({ kind: "unknown", status: attempt.status });
    return body;
  }
  throw apiErrorFromBody(attempt.status, attempt.body, attempt.retryAfter);
}

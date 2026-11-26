/** Summary endpoints (backend/app/api/v1/generation.py). */
import { apiRequest } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { SummaryOut } from "@/lib/api/types";

const path = (documentId: string) => `/documents/${encodeURIComponent(documentId)}/summary`;

/**
 * The document's summary, or null when none exists yet. The backend answers 404 both for "no summary" and for a
 * missing or foreign document, so callers load the document first (GET /documents/{id}) and call this only after it
 * was found (docs/F1_GATE.md 0.1).
 */
export async function getSummary(documentId: string, signal?: AbortSignal): Promise<SummaryOut | null> {
  try {
    return await apiRequest<SummaryOut>(path(documentId), { signal });
  } catch (error) {
    if (error instanceof ApiError && error.kind === "not_found") return null;
    throw error;
  }
}

/** 200 with the stored summary, or 202 with the queued/running generation; both carry SummaryOut. */
export function requestSummary(documentId: string, regenerate: boolean): Promise<SummaryOut> {
  return apiRequest<SummaryOut>(path(documentId), { method: "POST", body: { regenerate } });
}

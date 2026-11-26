/** Summary endpoints (backend/app/api/v1/generation.py). */
import { apiRequest } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { CourseSummaryList, CourseSummaryOut, SummaryOut } from "@/lib/api/types";

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

/**
 * Combined summaries (POST /courses/{id}/summaries): one summary grounded in the selected ready documents. The body
 * carries the explicit ids, in the reader's order, each once; the backend refuses (never trims) a bad selection.
 */
export function createCourseSummary(courseId: string, documentIds: readonly string[]): Promise<CourseSummaryOut> {
  return apiRequest<CourseSummaryOut>(`/courses/${encodeURIComponent(courseId)}/summaries`, {
    method: "POST",
    body: { document_ids: [...new Set(documentIds)] },
  });
}

export function getCourseSummary(summaryId: string, signal?: AbortSignal): Promise<CourseSummaryOut> {
  return apiRequest<CourseSummaryOut>(`/summaries/${encodeURIComponent(summaryId)}`, { signal });
}

export function listCourseSummaries(courseId: string, signal?: AbortSignal): Promise<CourseSummaryList> {
  return apiRequest<CourseSummaryList>(`/courses/${encodeURIComponent(courseId)}/summaries?limit=50`, { signal });
}

export function deleteCourseSummary(summaryId: string): Promise<void> {
  return apiRequest<void>(`/summaries/${encodeURIComponent(summaryId)}`, { method: "DELETE" });
}

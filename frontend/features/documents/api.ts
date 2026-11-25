/** Document endpoints (backend/app/api/v1/documents.py). Ids go in the path only, URL-encoded. */
import { apiDownload, apiRequest, query } from "@/lib/api/client";
import type { DocumentList, DocumentOut } from "@/lib/api/types";

const docPath = (documentId: string) => `/documents/${encodeURIComponent(documentId)}`;

export function listDocuments(courseId: string, limit: number, offset: number, signal?: AbortSignal): Promise<DocumentList> {
  return apiRequest<DocumentList>(`/courses/${encodeURIComponent(courseId)}/documents${query({ limit, offset })}`, { signal });
}

export function getDocument(documentId: string, signal?: AbortSignal): Promise<DocumentOut> {
  return apiRequest<DocumentOut>(docPath(documentId), { signal });
}

export function retryDocument(documentId: string): Promise<DocumentOut> {
  return apiRequest<DocumentOut>(`${docPath(documentId)}/retry`, { method: "POST" });
}

export function deleteDocument(documentId: string): Promise<void> {
  return apiRequest<void>(docPath(documentId), { method: "DELETE" });
}

export function downloadDocument(documentId: string, signal?: AbortSignal) {
  return apiDownload(`${docPath(documentId)}/file`, signal);
}

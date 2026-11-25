/**
 * Stable TanStack Query keys (gate GF0B-23). Every server resource has one key family, so a mutation can invalidate
 * exactly what it changed. Logout clears the whole cache (GF0A-12), so no key outlives the session that filled it.
 */

/** Page sizes: the backend default for courses (50) and its maximum for documents (100), so lists rarely page. */
export const COURSE_PAGE_SIZE = 50;
export const DOCUMENT_PAGE_SIZE = 100;

export const queryKeys = {
  courses: () => ["courses"] as const,
  courseList: (limit: number = COURSE_PAGE_SIZE) => ["courses", { limit }] as const,
  course: (courseId: string) => ["course", courseId] as const,
  documentsOf: (courseId: string) => ["documents", courseId] as const,
  documentList: (courseId: string, limit: number = DOCUMENT_PAGE_SIZE) => ["documents", courseId, { limit }] as const,
  document: (documentId: string) => ["document", documentId] as const,
};

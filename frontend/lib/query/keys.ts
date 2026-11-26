/**
 * Stable TanStack Query keys (gate GF0B-23). Every server resource has one key family, so a mutation can invalidate
 * exactly what it changed. Logout clears the whole cache (GF0A-12), so no key outlives the session that filled it.
 */

/** Page sizes: the backend default for courses (50) and its maximum for documents (100), so lists rarely page. */
export const COURSE_PAGE_SIZE = 50;
export const CONVERSATION_PAGE_SIZE = 50;
export const QUIZ_PAGE_SIZE = 50;
export const ATTEMPT_PAGE_SIZE = 50;
export const DOCUMENT_PAGE_SIZE = 100;

export const queryKeys = {
  courses: () => ["courses"] as const,
  courseList: (limit: number = COURSE_PAGE_SIZE) => ["courses", { limit }] as const,
  course: (courseId: string) => ["course", courseId] as const,
  documentsOf: (courseId: string) => ["documents", courseId] as const,
  documentList: (courseId: string, limit: number = DOCUMENT_PAGE_SIZE) => ["documents", courseId, { limit }] as const,
  document: (documentId: string) => ["document", documentId] as const,
  summary: (documentId: string) => ["summary", documentId] as const,
  conversationsOf: (courseId: string) => ["conversations", courseId] as const,
  conversationList: (courseId: string, limit: number = CONVERSATION_PAGE_SIZE) => ["conversations", courseId, { limit }] as const,
  conversation: (conversationId: string) => ["conversation", conversationId] as const,
  quizzesOf: (courseId: string) => ["quizzes", courseId] as const,
  quizList: (courseId: string, limit: number = QUIZ_PAGE_SIZE) => ["quizzes", courseId, { limit }] as const,
  quiz: (quizId: string) => ["quiz", quizId] as const,
  attemptsOf: (quizId: string) => ["attempts", quizId] as const,
  attemptList: (quizId: string, limit: number = ATTEMPT_PAGE_SIZE) => ["attempts", quizId, { limit }] as const,
  attempt: (attemptId: string) => ["attempt", attemptId] as const,
  attemptResults: (attemptId: string) => ["attempt-results", attemptId] as const,
};

/** Quiz and attempt endpoints (backend/app/api/v1/generation.py, attempts.py). Ids go in the path only, encoded. */
import { apiRequest, query } from "@/lib/api/client";
import type { AttemptDetail, AttemptList, AttemptResults, QuizDetail, QuizList, QuizOut, SavedAnswer } from "@/lib/api/types";

const e = encodeURIComponent;

export type QuizRequest = { title?: string; question_count: number; question_types: ("mcq" | "true_false")[]; document_ids?: string[] };
/** Exactly one field, as the backend requires: `choice` for multiple choice, `value` for true/false. */
export type AnswerPayload = { choice: number } | { value: boolean };

export const listQuizzes = (courseId: string, limit: number, offset: number, signal?: AbortSignal) =>
  apiRequest<QuizList>(`/courses/${e(courseId)}/quizzes${query({ limit, offset })}`, { signal });
export const createQuiz = (courseId: string, body: QuizRequest) => apiRequest<QuizOut>(`/courses/${e(courseId)}/quizzes`, { method: "POST", body });
export const getQuiz = (quizId: string, signal?: AbortSignal) => apiRequest<QuizDetail>(`/quizzes/${e(quizId)}`, { signal });
/** No body: the backend rejects any body on regenerate, start, submit and retry (`unexpected_body`). */
export const regenerateQuiz = (quizId: string) => apiRequest<QuizOut>(`/quizzes/${e(quizId)}/regenerate`, { method: "POST" });
export const deleteQuiz = (quizId: string) => apiRequest<void>(`/quizzes/${e(quizId)}`, { method: "DELETE" });
export const startAttempt = (quizId: string) => apiRequest<AttemptDetail>(`/quizzes/${e(quizId)}/attempts`, { method: "POST" });
export const listAttempts = (quizId: string, limit: number, offset: number, signal?: AbortSignal) =>
  apiRequest<AttemptList>(`/quizzes/${e(quizId)}/attempts${query({ limit, offset })}`, { signal });
export const getAttempt = (attemptId: string, signal?: AbortSignal) => apiRequest<AttemptDetail>(`/attempts/${e(attemptId)}`, { signal });
export const saveAnswer = (attemptId: string, questionId: string, body: AnswerPayload) =>
  apiRequest<SavedAnswer>(`/attempts/${e(attemptId)}/answers/${e(questionId)}`, { method: "PUT", body });
export const submitAttempt = (attemptId: string) => apiRequest<AttemptResults>(`/attempts/${e(attemptId)}/submit`, { method: "POST" });
export const getResults = (attemptId: string, signal?: AbortSignal) => apiRequest<AttemptResults>(`/attempts/${e(attemptId)}/results`, { signal });
export const retryMissed = (attemptId: string) => apiRequest<AttemptDetail>(`/attempts/${e(attemptId)}/retry-missed`, { method: "POST" });

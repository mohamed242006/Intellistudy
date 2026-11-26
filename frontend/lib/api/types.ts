/** Response and request shapes, taken from the generated backend schema (lib/api/schema.d.ts). Never hand-written. */
import type { components } from "./schema";

export type UserOut = components["schemas"]["UserOut"];
export type TokenResponse = components["schemas"]["TokenResponse"];
export type LoginRequest = components["schemas"]["LoginRequest"];
export type RegisterRequest = components["schemas"]["RegisterRequest"];

export type CourseOut = components["schemas"]["CourseOut"];
export type CourseList = components["schemas"]["CourseList"];
export type CourseCreate = components["schemas"]["CourseCreate"];
export type CourseUpdate = components["schemas"]["CourseUpdate"];
export type DocumentOut = components["schemas"]["DocumentOut"];
export type DocumentList = components["schemas"]["DocumentList"];
export type UploadResponse = components["schemas"]["UploadResponse"];
export type UploadedDocument = components["schemas"]["UploadedDocument"];

export type SummaryOut = components["schemas"]["SummaryOut"];
export type SummarySectionOut = components["schemas"]["SummarySection"];
export type SummaryCitation = components["schemas"]["SummaryCitation"];
export type ConversationOut = components["schemas"]["ConversationOut"];
export type ConversationDetail = components["schemas"]["ConversationDetail"];
export type ConversationList = components["schemas"]["ConversationList"];
export type MessageOut = components["schemas"]["MessageOut"];
export type CitationOut = components["schemas"]["CitationOut"];
export type SourceOut = components["schemas"]["SourceOut"];

export type QuizOut = components["schemas"]["QuizOut"];
export type QuizDetail = components["schemas"]["QuizDetail"];
export type QuizList = components["schemas"]["QuizList"];
export type QuestionOut = components["schemas"]["QuestionOut"];
export type AttemptOut = components["schemas"]["AttemptOut"];
export type AttemptDetail = components["schemas"]["AttemptDetail"];
export type AttemptList = components["schemas"]["AttemptList"];
export type AttemptResults = components["schemas"]["AttemptResults"];
export type ResultQuestion = components["schemas"]["ResultQuestion"];
export type SavedAnswer = components["schemas"]["SavedAnswer"];
export type AnswerOut = components["schemas"]["AnswerOut"];

/** Backend-shaped F2 fixtures (backend/app/api/v1/generation.py QuizOut/QuestionOut, attempts.py). */
import type { AttemptDetail, AttemptResults, QuestionOut, QuizDetail, ResultQuestion } from "@/lib/api/types";
import { COURSE_ID } from "./data";

export const QUIZ_ID = "88888888-8888-4888-8888-000000000001";
export const ATTEMPT_ID = "99999999-9999-4999-8999-000000000001";
export const Q1 = "aaaaaaaa-0000-4000-8000-000000000001";
export const Q2 = "aaaaaaaa-0000-4000-8000-000000000002";
export const Q3 = "aaaaaaaa-0000-4000-8000-000000000003";

export function question(overrides: Partial<QuestionOut> = {}): QuestionOut {
  return { id: Q1, position: 1, type: "mcq", stem: "Which word completes the statement?", options: ["alpha", "beta", "gamma", "delta"], topic: "Basics", difficulty: "easy", cognitive_level: "remember", ...overrides };
}

export const QUESTIONS: QuestionOut[] = [
  question(),
  question({ id: Q2, position: 2, type: "true_false", stem: "A stable queue needs utilisation below one.", options: null }),
  question({ id: Q3, position: 3, stem: "Which notation has three symbols?", options: ["Kendall", "Jackson", "Poisson", "Little"] }),
];

export function quiz(overrides: Partial<QuizDetail> = {}): QuizDetail {
  return {
    id: QUIZ_ID,
    course_id: COURSE_ID,
    title: "Practice quiz",
    status: "ready",
    invalid_reason: null,
    error_code: null,
    notice: null,
    requested_count: 3,
    question_count: 3,
    question_types: ["mcq", "true_false"],
    source_document_ids: ["33333333-3333-4333-8333-000000000001"],
    model: "secret-model-name",
    generated_at: "2026-11-26T10:00:00Z",
    created_at: "2026-11-26T09:59:00Z",
    questions: QUESTIONS,
    ...overrides,
  };
}

export function attempt(overrides: Partial<AttemptDetail> = {}): AttemptDetail {
  return {
    id: ATTEMPT_ID,
    quiz_id: QUIZ_ID,
    course_id: COURSE_ID,
    status: "in_progress",
    expired_reason: null,
    parent_attempt_id: null,
    question_count: 3,
    answered_count: 0,
    score: null,
    max_score: 3,
    started_at: "2026-11-26T10:01:00Z",
    submitted_at: null,
    questions: QUESTIONS,
    answers: [],
    ...overrides,
  };
}

export function resultQuestion(overrides: Partial<ResultQuestion> = {}): ResultQuestion {
  return {
    question_id: Q1,
    position: 1,
    type: "mcq",
    stem: "Which word completes the statement?",
    options: ["alpha", "beta", "gamma", "delta"],
    topic: "Basics",
    difficulty: "easy",
    cognitive_level: "remember",
    answered: true,
    answer: { choice: 1, value: null },
    correct: false,
    correct_answer: { choice: 0, value: null },
    evidence: "The statement uses alpha.",
    citation: { document_id: "d", file_name: "notes.pdf", citation_label: "p. 1", page: 1, slide: null },
    rationale: "The cited sentence uses alpha.",
    rationale_chosen: "Beta belongs to another statement.",
    explanation_source: "generated",
    ...overrides,
  };
}

export function results(overrides: Partial<AttemptResults> = {}): AttemptResults {
  return {
    attempt_id: ATTEMPT_ID,
    quiz_id: QUIZ_ID,
    parent_attempt_id: null,
    score: 1,
    max_score: 3,
    percent: 33.3,
    time_spent_seconds: 60,
    started_at: "2026-11-26T10:01:00Z",
    submitted_at: "2026-11-26T10:02:00Z",
    topics: [{ topic: "Basics", score: 1, max_score: 3 }],
    questions: [
      resultQuestion(),
      resultQuestion({ question_id: Q2, position: 2, type: "true_false", stem: "A stable queue needs utilisation below one.", options: null, answer: { choice: null, value: true }, correct: true, correct_answer: { choice: null, value: true }, rationale: "Says exactly this.", rationale_chosen: null }),
      resultQuestion({ question_id: Q3, position: 3, answered: false, answer: null, correct: false, correct_answer: { choice: 0, value: null }, rationale_chosen: null }),
    ],
    ...overrides,
  };
}

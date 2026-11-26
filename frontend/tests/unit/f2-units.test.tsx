import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AnswerChoice, AnswerReviewRow } from "@/design-system/components/AnswerOption";
import { QuizBar } from "@/design-system/compositions/QuizBar";
import { MAX_POLL_FAILURES } from "@/features/documents/polling";
import { MAX_QUESTIONS, MAX_QUIZ_DOCUMENTS, MIN_QUESTIONS, validateQuizForm, type QuizForm } from "@/features/quiz/components/QuizListPage";
import { attemptHref } from "@/features/quiz/components/QuizPage";
import { reviewRows, verdictOf } from "@/features/quiz/components/ReviewPage";
import { generationPollDelay, payloadOf } from "@/features/quiz/hooks";
import { generationFailure, quizError } from "@/features/quiz/messages";
import { ERRORS } from "@/features/quiz/strings";
import { ApiError, apiErrorFromBody } from "@/lib/api/errors";
import { queryKeys } from "@/lib/query/keys";
import { resultQuestion } from "../helpers/f2-data";

const REPO = join(process.cwd(), "..");
const read = (path: string) => readFileSync(join(REPO, path), "utf8");
const form = (overrides: Partial<QuizForm> = {}): QuizForm => ({ title: "", count: "10", mcq: true, trueFalse: true, documents: ["doc-0"], ...overrides });
const READY = Array.from({ length: 25 }, (_, i) => ({ id: `doc-${i}` }));

describe("GF2-03 generation form", () => {
  it("GF2-03 mirrors QuizCreate: count 5-30, at least one type, title ≤200, 1-20 ready files", () => {
    const schema = read("backend/app/api/v1/generation.py");
    expect(schema).toContain("question_count: Annotated[int, Field(ge=MIN_QUESTIONS, le=MAX_QUESTIONS)] = 10");
    expect(schema).toContain("title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None");
    expect(read("backend/app/services/quizgen.py")).toContain("MIN_QUESTIONS, MAX_QUESTIONS = 5, 30");
    expect(read("backend/app/services/generation.py")).toContain("MAX_QUIZ_DOCUMENTS = 20");
    expect([MIN_QUESTIONS, MAX_QUESTIONS, MAX_QUIZ_DOCUMENTS]).toEqual([5, 30, 20]);

    // the selection is always explicit: "Select all ready files" sends every ready id, each once
    expect(validateQuizForm(form(), READY)).toEqual({ request: { question_count: 10, question_types: ["mcq", "true_false"], document_ids: ["doc-0"] }, errors: {} });
    expect(validateQuizForm(form({ documents: ["doc-2", "doc-1", "doc-2"] }), READY).request?.document_ids).toEqual(["doc-2", "doc-1"]);
    expect(validateQuizForm(form({ title: "  Midterm  ", mcq: false, documents: ["doc-1", "foreign"] }), READY).request).toEqual({
      title: "Midterm",
      question_count: 10,
      question_types: ["true_false"],
      document_ids: ["doc-1"], // ids that are not ready files of this course are never sent
    });
    for (const count of ["4", "31", "", "7.5", "1e1", "abc"]) expect(validateQuizForm(form({ count }), READY).errors.count, count).toBeDefined();
    expect(validateQuizForm(form({ mcq: false, trueFalse: false }), READY).errors.types).toBeDefined();
    expect(validateQuizForm(form({ title: "x".repeat(201) }), READY).errors.title).toBeDefined();
    expect(validateQuizForm(form({ documents: [] }), READY).errors.files).toBeDefined();
    expect(validateQuizForm(form({ documents: ["foreign"] }), READY).errors.files).toBeDefined();
    expect(validateQuizForm(form({ documents: READY.slice(0, 21).map((d) => d.id) }), READY).errors.files).toBeDefined();
  });
});

describe("GF2-05 generation polling", () => {
  it("GF2-05 polls every 2 s only while generating, backs off, and stops after repeated failures", () => {
    expect(generationPollDelay(true, 0)).toBe(2000);
    expect(generationPollDelay(true, 2)).toBe(8000);
    expect(generationPollDelay(true, 9)).toBe(false);
    expect(generationPollDelay(true, MAX_POLL_FAILURES)).toBe(false);
    expect(generationPollDelay(false, 0)).toBe(false);
  });

  it("GF2-05 every failure code of a quiz job has fixed copy", () => {
    const generation = read("backend/app/services/generation.py");
    for (const code of ["insufficient_material", "llm_unavailable", "token_budget", "internal_error"]) {
      expect(generation).toContain(`"${code}"`);
      expect(generationFailure(code)).toBe(ERRORS[code]);
    }
    expect(generationFailure("something_new")).toBe(ERRORS.internal_error);
  });
});

describe("GF2-08 GF2-15 answer options", () => {
  it("GF2-08 a choice is a labelled native radio (arrow keys, form semantics) with a visible selected state", async () => {
    const onChange = vi.fn();
    render(
      <fieldset>
        <legend>Pick</legend>
        <AnswerChoice name="q" value="0" label="alpha" checked onChange={onChange} />
        <AnswerChoice name="q" value="1" label="beta" checked={false} onChange={onChange} />
      </fieldset>,
    );
    expect(screen.getByRole("radio", { name: "alpha" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "alpha" }).closest("label")).toHaveAttribute("data-selected", "true");
    await userEvent.click(screen.getByRole("radio", { name: "beta" }));
    expect(onChange).toHaveBeenCalled();
  });

  it("GF2-15 review rows say Correct / Incorrect in words, never colour alone", () => {
    render(
      <>
        <AnswerReviewRow label="alpha" verdict="correct" verdictText="Correct" />
        <AnswerReviewRow label="beta" verdict="incorrect" verdictText="Incorrect" note="Your answer" />
      </>,
    );
    expect(screen.getByText("Correct")).toBeVisible();
    expect(screen.getByText("Incorrect")).toBeVisible();
    expect(screen.getByText("Your answer")).toBeVisible();
  });

  it("GF2-15 verdicts and rows come only from the backend's fields", () => {
    expect(verdictOf({ correct: true, answered: true })).toEqual({ tone: "success", label: "Correct" });
    expect(verdictOf({ correct: false, answered: true })).toEqual({ tone: "danger", label: "Incorrect" });
    expect(verdictOf({ correct: false, answered: false })).toEqual({ tone: "neutral", label: "Not answered" });
    const rows = reviewRows(resultQuestion())!;
    expect(rows.map((r) => [r.label, r.verdict, r.note ?? null])).toEqual([
      ["alpha", "correct", null],
      ["beta", "incorrect", "Your answer"],
      ["gamma", "neutral", null],
      ["delta", "neutral", null],
    ]);
    const tf = reviewRows(resultQuestion({ type: "true_false", options: null, answer: { choice: null, value: false }, correct_answer: { choice: null, value: true } }))!;
    expect(tf.map((r) => [r.label, r.verdict])).toEqual([["True", "correct"], ["False", "incorrect"]]);
    expect(reviewRows(resultQuestion({ correct_answer: { choice: null, value: null } }))).toBeNull(); // unknown shape: no verdict
    expect(reviewRows(resultQuestion({ type: "short_answer" as never }))).toBeNull();
  });
});

describe("GF2-09 answer payloads", () => {
  it("GF2-09 a saved answer maps back to exactly one field", () => {
    expect(payloadOf({ choice: 2, value: null })).toEqual({ choice: 2 });
    expect(payloadOf({ choice: null, value: false })).toEqual({ value: false });
    expect(payloadOf({ choice: null, value: null })).toBeUndefined();
    expect(read("backend/app/api/v1/attempts.py")).toContain('"""``choice`` (0-3) for multiple choice, ``value`` for true/false; exactly one (G5-ATT-05)."""');
  });
});

describe("GF2-10 quiz bar", () => {
  it("GF2-10 shows the position in text and a labelled progress bar", () => {
    render(<QuizBar exit={<button>Exit quiz</button>} title="Quiz · Queueing" subtitle="Practice quiz · 3 questions" position="Question 2 of 3" progress={66.7} progressLabel="Question 2 of 3" />);
    expect(screen.getByText("Question 2 of 3", { selector: "span" })).toBeVisible();
    expect(screen.getByRole("progressbar", { name: "Question 2 of 3" })).toHaveAttribute("aria-valuenow", "67");
  });
});

describe("GF2-19 error copy", () => {
  it("GF2-19 every backend quiz and attempt code maps to fixed copy; problem bodies are never shown", () => {
    const sources = read("backend/app/services/attempts.py") + read("backend/app/services/generation.py") + read("backend/app/api/v1/attempts.py");
    for (const code of ["quiz_not_ready", "attempt_submitted", "attempt_expired", "attempt_not_submitted", "invalid_answer", "nothing_to_retry", "quiz_changed", "attempt_in_progress", "document_not_ready", "too_many_documents"]) {
      expect(sources, code).toContain(`"${code}"`);
      expect(quizError(apiErrorFromBody(409, { type: `about:blank#${code}`, detail: "Traceback /srv/x" }, null))).toBe(ERRORS[code]);
    }
    expect(quizError(apiErrorFromBody(429, { type: "about:blank#rate_limited" }, "90"))).toBe("Too many requests. Try again in 2 minutes.");
    expect(quizError(apiErrorFromBody(429, { type: "about:blank#token_budget" }, "3600"))).toBe(ERRORS.token_budget);
    expect(quizError(apiErrorFromBody(503, { type: "about:blank#llm_unavailable" }, null))).toBe(ERRORS.llm_unavailable);
    expect(quizError(new ApiError({ kind: "network", status: 0 }))).toBe(ERRORS.network);
    expect(quizError(apiErrorFromBody(500, { type: "about:blank", detail: "SQL error" }, null))).toBe(ERRORS.fallback);
    expect(quizError(new Error("x"))).toBe(ERRORS.fallback);
  });
});

describe("GF2-21 query keys", () => {
  it("GF2-21 quiz and attempt keys carry their owning resource", () => {
    expect(queryKeys.quizList("c1")).toEqual(["quizzes", "c1", { limit: 50 }]);
    expect(queryKeys.quizList("c1").slice(0, 2)).toEqual(queryKeys.quizzesOf("c1"));
    expect(queryKeys.quiz("q1")).toEqual(["quiz", "q1"]);
    expect(queryKeys.attemptList("q1")).toEqual(["attempts", "q1", { limit: 50 }]);
    expect(queryKeys.attempt("a1")).toEqual(["attempt", "a1"]);
    expect(queryKeys.attemptResults("a1")).toEqual(["attempt-results", "a1"]);
    expect(attemptHref({ id: "a1", quiz_id: "q1", status: "submitted" })).toBe("/attempts/a1/review");
    expect(attemptHref({ id: "a1", quiz_id: "q1", status: "in_progress" })).toBe("/quizzes/q1/attempts/a1");
  });
});

describe("GF2-28 deterministic quiz provider", () => {
  it("GF2-28 the E2E stub answers quiz prompts through the backend's real validation; no real model or key", () => {
    const stub = readFileSync(join(process.cwd(), "tests", "e2e", "fixtures", "stub_llm.py"), "utf8");
    expect(stub).toContain('if "practice questions" in system:');
    expect(stub).toContain("DETERMINISTIC TEST PROVIDER");
    expect(read("backend/app/services/quizgen.py")).toContain("You are IntelliStudy, writing practice questions from ONLY the numbered sources provided.");
    expect(stub).not.toMatch(/api\.deepseek|openai\.com|API_KEY/);
    const harness = readFileSync(join(process.cwd(), "scripts", "e2e-backend.sh"), "utf8");
    expect(harness).toContain("INTELLISTUDY_LLM_PROVIDER=local");
    expect(harness).toContain("SentenceTransformer(EMBEDDING_MODEL); CrossEncoder(DEFAULT_RERANKER_MODEL)");
    expect(readFileSync(join(process.cwd(), "tests", "e2e", "fixtures", "make_fixtures.py"), "utf8")).toContain('"quiz-notes.pdf"');
  });
});

describe("GF2-29 CI regression: document title", () => {
  it("GF2-29 metadata is rendered blocking in <head> for every user agent, so client navigations never drop the <title>", () => {
    const config = readFileSync(join(process.cwd(), "next.config.ts"), "utf8");
    expect(config).toContain("htmlLimitedBots: /.*/,");
    const spec = readFileSync(join(process.cwd(), "tests", "e2e", "courses.spec.ts"), "utf8");
    expect(spec).toContain('expect(await titleGaps(page), "the document title is never missing after load").toEqual([]);');
    expect(spec).toContain(`expect(payload, "metadata must not be streamed as a deferred row").not.toContain('{"metadata":');`);
  });
});

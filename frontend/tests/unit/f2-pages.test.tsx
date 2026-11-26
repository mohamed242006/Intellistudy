import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AttemptPage } from "@/features/quiz/components/AttemptPage";
import { QuizListPage } from "@/features/quiz/components/QuizListPage";
import { QuizPage } from "@/features/quiz/components/QuizPage";
import { ReviewPage } from "@/features/quiz/components/ReviewPage";
import type { AttemptDetail } from "@/lib/api/types";
import { tokenStore } from "@/lib/auth/token-store";
import { deferred, renderPage, signedInBackend } from "../helpers/app";
import { COURSE_ID, OTHER_ID, course, doc, page } from "../helpers/data";
import { ATTEMPT_ID, Q1, QUIZ_ID, attempt, quiz, results } from "../helpers/f2-data";
import { HOSTILE_AI } from "../helpers/f1-data";
import { json, problem } from "../helpers/fake-backend";
import { nav } from "../helpers/navigation";

vi.mock("next/navigation", async () => (await import("../helpers/navigation")).navigationMock());
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode; scroll?: boolean }) => {
    const attributes: Record<string, unknown> = { ...rest };
    delete attributes.scroll;
    return (
      <a href={href} {...attributes}>
        {children}
      </a>
    );
  },
}));

beforeEach(() => tokenStore.clear());
afterEach(() => vi.useRealTimers());

const DOC_A = doc({ file_name: "quiz-notes.pdf" });
const DOC_B = doc({ file_name: "unready.pdf", status: "embedding" });
const QUIZ = `GET /quizzes/${QUIZ_ID}`;
const ATTEMPT = `GET /attempts/${ATTEMPT_ID}`;
const RESULTS = `GET /attempts/${ATTEMPT_ID}/results`;

function base() {
  return signedInBackend()
    .on(`GET /courses/${COURSE_ID}`, () => json(200, course()))
    .on(`GET /courses/${COURSE_ID}/documents`, () => json(200, page([DOC_A, DOC_B], 100)))
    .on(`GET /courses/${COURSE_ID}/quizzes`, () => json(200, page([])))
    .on(`GET /quizzes/${QUIZ_ID}/attempts`, () => json(200, page([])));
}

const openList = (search = "") => renderPage(<QuizListPage courseId={COURSE_ID} />, { shell: "rail", path: `/courses/${COURSE_ID}/quizzes`, search });
const openQuiz = (id = QUIZ_ID) => renderPage(<QuizPage quizId={id} />, { shell: "rail", path: `/quizzes/${id}` });
const openAttempt = (quizId = QUIZ_ID, attemptId = ATTEMPT_ID) => renderPage(<AttemptPage quizId={quizId} attemptId={attemptId} />, { shell: "rail", path: `/quizzes/${quizId}/attempts/${attemptId}` });
const openReview = (id = ATTEMPT_ID) => renderPage(<ReviewPage attemptId={id} />, { shell: "rail", path: `/attempts/${id}/review` });
const postBody = (b: ReturnType<typeof base>, path: string) => b.calls.filter((c) => c.method !== "GET" && c.path === path);

describe("GF2-01 GF2-02 GF2-03 GF2-04 course quizzes", () => {
  it("GF2-02 lists the backend's quizzes with status in text, and shows the empty state", async () => {
    const b = base().on(`GET /courses/${COURSE_ID}/quizzes`, () =>
      json(200, page([quiz({ id: QUIZ_ID, title: "Midterm", status: "ready", question_count: 7 }), quiz({ id: OTHER_ID, title: "Draft", status: "generating" }), quiz({ id: "77777777-7777-4777-8777-000000000001", title: "Broken", status: "failed" })])),
    );
    openList();
    const link = await screen.findByRole("link", { name: /Midterm/ });
    expect(link).toHaveAttribute("href", `/quizzes/${QUIZ_ID}`);
    expect(link).toHaveTextContent("MidtermReady7 questions");
    expect(screen.getByRole("link", { name: /Draft/ })).toHaveTextContent("Generating");
    expect(screen.getByRole("link", { name: /Broken/ })).toHaveTextContent("Failed");
    expect(document.body.textContent).not.toMatch(/secret-model-name|mastery|%/);
    expect(b.calls.find((c) => c.path.endsWith("/quizzes"))!.search).toBe("?limit=50&offset=0");
  });

  it("GF2-01 GF2-03 a file from the workspace is preselected; only ready files can be chosen", async () => {
    base();
    openList(`document=${DOC_A.id}`);
    expect(await screen.findByRole("radio", { name: "Only these files" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "quiz-notes.pdf" })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "unready.pdf" })).toBeNull();
    expect(await screen.findByRole("heading", { name: "No quizzes yet" })).toBeVisible();
  });

  it("GF2-04 sends one POST with exactly the backend fields, blocks double submission and opens the new quiz", async () => {
    const hold = deferred<void>();
    const b = base().on(`POST /courses/${COURSE_ID}/quizzes`, () => hold.promise.then(() => json(202, quiz({ status: "generating", questions: [] }))));
    openList();
    const count = await screen.findByLabelText("Number of questions");
    await userEvent.clear(count);
    await userEvent.type(count, "8");
    await userEvent.type(screen.getByLabelText("Title (optional)"), "  Week 3  ");
    await userEvent.click(screen.getByRole("checkbox", { name: "Multiple choice" }));
    const submit = screen.getByRole("button", { name: "Generate quiz" });
    await userEvent.click(submit);
    await userEvent.click(submit);
    expect(postBody(b, `/courses/${COURSE_ID}/quizzes`)).toHaveLength(1);
    expect(postBody(b, `/courses/${COURSE_ID}/quizzes`)[0]!.body).toEqual({ title: "Week 3", question_count: 8, question_types: ["true_false"] });
    hold.resolve();
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/quizzes/${QUIZ_ID}`));
  });

  it("GF2-03 GF2-19 invalid input is refused before sending; a backend refusal and a rate limit show fixed copy", async () => {
    const b = base().on(`POST /courses/${COURSE_ID}/quizzes`, () => problem(429, "rate_limited", "x", { "Retry-After": "600" }));
    openList();
    const count = await screen.findByLabelText("Number of questions");
    await userEvent.clear(count);
    await userEvent.type(count, "40");
    await userEvent.click(screen.getByRole("button", { name: "Generate quiz" }));
    expect(screen.getByText("Choose a number from 5 to 30.")).toBeVisible();
    expect(count).toHaveAttribute("aria-invalid", "true");
    expect(postBody(b, `/courses/${COURSE_ID}/quizzes`)).toHaveLength(0);
    await userEvent.clear(count);
    await userEvent.type(count, "10");
    await userEvent.click(screen.getByRole("button", { name: "Generate quiz" }));
    expect(await screen.findByText("Too many requests. Try again in 10 minutes.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Generate quiz" })).toBeDisabled();
  });
});

describe("GF2-05 GF2-06 GF2-07 GF2-18 quiz page", () => {
  it("GF2-05 generating is polled to ready; the fewer-questions notice is shown; internals are hidden", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    let state = quiz({ status: "generating", questions: [], question_count: 0 });
    base().on(QUIZ, () => json(200, state));
    openQuiz();
    expect(await screen.findByText("Writing questions…")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Start quiz" })).toBeNull();
    state = quiz({ requested_count: 10, question_count: 7 });
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    expect(await screen.findByRole("button", { name: "Start quiz" })).toBeVisible();
    expect(screen.getByText("Your materials supported 7 good questions instead of the 10 requested.")).toBeVisible();
    expect(document.body.textContent).not.toContain("secret-model-name");
  });

  it("GF2-05 failed and invalid quizzes say why, with Regenerate and no Start", async () => {
    base().on(QUIZ, () => json(200, quiz({ status: "failed", error_code: "insufficient_material", questions: [] })));
    const view = openQuiz();
    expect(await screen.findByText("The chosen files didn’t support at least 5 good questions. Try more files.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Start quiz" })).toBeNull();
    view.unmount();
    base().on(QUIZ, () => json(200, quiz({ status: "invalid", invalid_reason: "source_deleted", notice: "A source document was deleted. Regenerate this quiz to use it again.", questions: [] })));
    openQuiz();
    expect(await screen.findByText("A source document was deleted. Regenerate this quiz to use it again.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeVisible();
  });

  it("GF2-07 GF2-18 Start sends no body and opens the attempt; an attempt in progress makes it Continue; history shows backend scores", async () => {
    const b = base()
      .on(QUIZ, () => json(200, quiz()))
      .on(`GET /quizzes/${QUIZ_ID}/attempts`, () =>
        json(200, page([attempt({ answered_count: 1 }), attempt({ id: OTHER_ID, status: "submitted", score: 2, submitted_at: "2026-11-26T10:00:00Z", questions: null, answers: null })])),
      )
      .on(`POST /quizzes/${QUIZ_ID}/attempts`, () => json(200, attempt()));
    openQuiz();
    const history = await screen.findByRole("region", { name: "Attempts" });
    await within(history).findByText("2 of 3 correct");
    expect(within(history).getByText("1 of 3 answered")).toBeVisible();
    expect(within(history).getByRole("link", { name: /Submitted/ })).toHaveAttribute("href", `/attempts/${OTHER_ID}/review`);
    await userEvent.click(screen.getByRole("button", { name: "Continue quiz" }));
    const start = postBody(b, `/quizzes/${QUIZ_ID}/attempts`)[0]!;
    expect(start.body).toBeUndefined();
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/quizzes/${QUIZ_ID}/attempts/${ATTEMPT_ID}`));
  });

  it("GF2-07 GF2-19 a quiz that is not ready to take shows the backend's reason in fixed copy", async () => {
    base().on(QUIZ, () => json(200, quiz())).on(`POST /quizzes/${QUIZ_ID}/attempts`, () => problem(409, "quiz_not_ready", "A source document of this quiz is not ready."));
    openQuiz();
    await userEvent.click(await screen.findByRole("button", { name: "Start quiz" }));
    expect(await screen.findByText("This quiz isn’t ready to be taken.")).toBeVisible();
  });

  it("GF2-06 regenerate and delete ask first; delete returns to the course quizzes", async () => {
    const b = base()
      .on(QUIZ, () => json(200, quiz()))
      .on(`POST /quizzes/${QUIZ_ID}/regenerate`, () => json(202, quiz({ status: "generating", questions: [] })))
      .on(`DELETE /quizzes/${QUIZ_ID}`, () => new Response(null, { status: 204 }));
    openQuiz();
    await userEvent.click(await screen.findByRole("button", { name: "Regenerate" }));
    const dialog = screen.getByRole("dialog", { name: "Regenerate this quiz?" });
    expect(dialog).toHaveAccessibleDescription(/An attempt in progress ends/);
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.click(within(dialog).getByRole("button", { name: "Regenerate" }));
    expect(await screen.findByText("Writing questions…")).toBeVisible();
    expect(postBody(b, `/quizzes/${QUIZ_ID}/regenerate`)[0]!.body).toBeUndefined();
    await userEvent.click(screen.getByRole("button", { name: "Delete quiz" }));
    await userEvent.click(within(screen.getByRole("dialog", { name: "Delete this quiz?" })).getByRole("button", { name: "Delete quiz" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(`/courses/${COURSE_ID}/quizzes`));
  });
});

function takingBackend(state: AttemptDetail = attempt()) {
  return base().on(QUIZ, () => json(200, quiz())).on(ATTEMPT, () => json(200, state));
}

describe("GF2-08 GF2-09 GF2-10 GF2-11 taking a quiz", () => {
  it("GF2-08 GF2-10 one question per screen as a fieldset with its stem as legend; navigator and position in text", async () => {
    takingBackend();
    openAttempt();
    const group = await screen.findByRole("group", { name: /MULTIPLE CHOICE\s*Which word completes the statement\?/ });
    expect(within(group).getAllByRole("radio").map((r) => r.closest("label")!.textContent)).toEqual(["alpha", "beta", "gamma", "delta"]);
    expect(screen.getByText("Question 1 of 3", { selector: "span" })).toBeVisible();
    const navigator = screen.getByRole("navigation", { name: "Questions" });
    expect(within(navigator).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual(["Question 1, not answered", "Question 2, not answered", "Question 3, not answered"]);
    expect(within(navigator).getByRole("button", { name: "Question 1, not answered" })).toHaveAttribute("aria-current", "step");
    await userEvent.click(screen.getByRole("button", { name: "Next question" }));
    const tf = screen.getByRole("group", { name: /TRUE OR FALSE/ });
    expect(within(tf).getAllByRole("radio").map((r) => r.closest("label")!.textContent)).toEqual(["True", "False"]);
    expect(screen.getByRole("heading", { level: 2, name: "A stable queue needs utilisation below one." })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(screen.getByRole("heading", { level: 2, name: "Which word completes the statement?" })).toHaveFocus();
  });

  it("GF2-09 saves on selection with the exact payload; Saved only after the 200; the last choice wins without races", async () => {
    const first = deferred<void>();
    let calls = 0;
    const b = takingBackend().on(`PUT /attempts/${ATTEMPT_ID}/answers/${Q1}`, (_url, init) => {
      calls += 1;
      const body = JSON.parse(String(init.body)) as { choice: number };
      const reply = () => json(200, { question_id: Q1, answer: { choice: body.choice, value: null }, saved_at: "2026-11-26T10:02:00Z" });
      return calls === 1 ? first.promise.then(reply) : reply();
    });
    openAttempt();
    await userEvent.click(await screen.findByRole("radio", { name: "beta" }));
    expect(screen.getByText("Saving…")).toBeVisible();
    await userEvent.click(screen.getByRole("radio", { name: "delta" }));
    expect(b.calls.filter((c) => c.method === "PUT")).toHaveLength(1); // the newer choice waits for the first request
    first.resolve();
    await waitFor(() => expect(b.calls.filter((c) => c.method === "PUT")).toHaveLength(2));
    expect(b.calls.filter((c) => c.method === "PUT").map((c) => c.body)).toEqual([{ choice: 1 }, { choice: 3 }]);
    expect(await screen.findByText("Saved")).toBeVisible();
    expect(screen.getByRole("radio", { name: "delta" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Question 1, answered" })).toBeVisible();
  });

  it("GF2-09 a failed save says so, keeps the choice and offers Try again; nothing is retried automatically", async () => {
    let fail = true;
    const b = takingBackend().on(`PUT /attempts/${ATTEMPT_ID}/answers/${Q1}`, () => (fail ? problem(409, "attempt_expired") : json(200, { question_id: Q1, answer: { choice: 0, value: null }, saved_at: "x" })));
    openAttempt();
    await userEvent.click(await screen.findByRole("radio", { name: "alpha" }));
    expect(await screen.findByText("Not saved: This attempt ended because the quiz was regenerated.")).toBeVisible();
    expect(b.calls.filter((c) => c.method === "PUT")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Question 1, not answered" })).toBeVisible();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Saved")).toBeVisible();
  });

  it("GF2-11 before submission nothing about correctness exists in the page and results are never requested", async () => {
    const b = takingBackend(attempt({ answers: [{ question_id: Q1, answer: { choice: 2, value: null }, saved_at: "x" }], answered_count: 1 }));
    openAttempt();
    await screen.findByRole("navigation", { name: "Questions" });
    expect(screen.getByRole("button", { name: "Question 1, answered" })).toBeVisible();
    expect(screen.getByRole("heading", { level: 2, name: "A stable queue needs utilisation below one." })).toBeVisible(); // resumed at the first unanswered
    expect(b.count(RESULTS)).toBe(0);
    expect(document.body.textContent).not.toMatch(/\bCorrect\b|\bIncorrect\b|WHY|EVIDENCE|rationale|score/);
    expect(document.querySelector("[data-verdict]")).toBeNull();
  });

  it("GF2-08 an unknown question type is shown without any input", async () => {
    takingBackend(attempt({ questions: [{ id: Q1, position: 1, type: "short_answer" as never, stem: "Explain weaving.", options: null, topic: "t", difficulty: "easy", cognitive_level: "remember" }] }));
    openAttempt();
    expect(await screen.findByText("This question type isn’t supported here, so it can’t be answered on this page.")).toBeVisible();
    expect(screen.queryByRole("radio")).toBeNull();
  });
});

describe("GF2-12 GF2-17 submission and attempt states", () => {
  it("GF2-12 the confirmation states the real unanswered count; one POST; results cached from the response; then review", async () => {
    const hold = deferred<void>();
    const b = takingBackend(attempt({ answers: [{ question_id: Q1, answer: { choice: 0, value: null }, saved_at: "x" }] })).on(`POST /attempts/${ATTEMPT_ID}/submit`, () =>
      hold.promise.then(() => json(200, results())),
    );
    const { queryClient } = openAttempt();
    await userEvent.click((await screen.findAllByRole("button", { name: "Finish quiz" }))[0]!);
    const dialog = screen.getByRole("dialog", { name: "Submit your answers?" });
    expect(dialog).toHaveAccessibleDescription(/2 questions are not answered and will count as incorrect/);
    const submit = within(dialog).getByRole("button", { name: "Submit answers" });
    await userEvent.click(submit);
    await userEvent.click(submit);
    expect(postBody(b, `/attempts/${ATTEMPT_ID}/submit`)).toHaveLength(1);
    expect(postBody(b, `/attempts/${ATTEMPT_ID}/submit`)[0]!.body).toBeUndefined();
    hold.resolve();
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(`/attempts/${ATTEMPT_ID}/review`));
    expect(queryClient.getQueryData(["attempt-results", ATTEMPT_ID])).toEqual(results());
  });

  it("GF2-17 a submitted attempt opens the review; an expired one can't be answered", async () => {
    takingBackend(attempt({ status: "submitted", questions: null, answers: null, score: 1 }));
    const view = openAttempt();
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith(`/attempts/${ATTEMPT_ID}/review`));
    view.unmount();
    takingBackend(attempt({ status: "expired", expired_reason: "quiz_regenerated", questions: null, answers: null }));
    openAttempt();
    expect(await screen.findByRole("heading", { name: "This attempt has ended" })).toBeVisible();
    expect(screen.queryByRole("radio")).toBeNull();
  });

  it("GF2-17 the review of an attempt in progress offers to continue it instead of results", async () => {
    const b = base().on(ATTEMPT, () => json(200, attempt())).on(QUIZ, () => json(200, quiz()));
    openReview();
    expect(await screen.findByRole("link", { name: "Continue quiz" })).toHaveAttribute("href", `/quizzes/${QUIZ_ID}/attempts/${ATTEMPT_ID}`);
    expect(b.count(RESULTS)).toBe(0);
  });
});

describe("GF2-14 GF2-15 GF2-16 results and review", () => {
  const submitted = attempt({ status: "submitted", questions: null, answers: null, score: 1, submitted_at: "x" });

  it("GF2-14 GF2-15 shows only the backend's score, topics and per-question verdicts; the first wrong answer is open", async () => {
    base().on(ATTEMPT, () => json(200, submitted)).on(QUIZ, () => json(200, quiz())).on(RESULTS, () => json(200, results()));
    openReview();
    expect(await screen.findByRole("heading", { level: 2, name: "1 of 3 correct" })).toBeVisible();
    expect(screen.getByText("33.3%")).toBeVisible();
    expect(screen.getByText("1 of 3", { selector: "span" })).toBeVisible();
    const toggles = screen.getAllByRole("button", { expanded: true });
    expect(toggles).toHaveLength(1);
    expect(toggles[0]).toHaveTextContent("IncorrectQuestion 1 of 3");
    expect(screen.getByRole("button", { name: /Correct.*Question 2 of 3/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: /Not answered.*Question 3 of 3/ })).toBeVisible();
    const open = within(document.querySelector<HTMLElement>('[data-result="1"]')!);
    expect(open.getByText("The cited sentence uses alpha.")).toBeVisible();
    expect(open.getByText("Beta belongs to another statement.")).toBeVisible();
    expect(open.getByText("The statement uses alpha.")).toBeVisible();
    expect(open.getByText("notes.pdf")).toBeVisible();
    expect(open.getByText(/Explanation written by the AI/)).toBeVisible();
    expect(within(document.querySelector<HTMLElement>('[data-result="2"]')!).getByText("Says exactly this.")).not.toBeVisible(); // collapsed
  });

  it("GF2-16 Retry wrong answers creates the backend's retry attempt; a full score hides it; an attempt in progress can be continued", async () => {
    const child = attempt({ id: OTHER_ID, parent_attempt_id: ATTEMPT_ID });
    let reply: () => Response = () => json(201, child);
    const b = base().on(ATTEMPT, () => json(200, submitted)).on(QUIZ, () => json(200, quiz())).on(RESULTS, () => json(200, results()))
      .on(`POST /attempts/${ATTEMPT_ID}/retry-missed`, () => reply())
      .on(`POST /quizzes/${QUIZ_ID}/attempts`, () => json(200, attempt()));
    const view = openReview();
    await userEvent.click(await screen.findByRole("button", { name: "Retry wrong answers" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/quizzes/${QUIZ_ID}/attempts/${OTHER_ID}`));
    expect(postBody(b, `/attempts/${ATTEMPT_ID}/retry-missed`)[0]!.body).toBeUndefined();
    view.unmount();
    reply = () => problem(409, "attempt_in_progress", "Finish the attempt in progress first.");
    openReview();
    await userEvent.click(await screen.findByRole("button", { name: "Retry wrong answers" }));
    await userEvent.click(await screen.findByRole("button", { name: "Continue the attempt in progress" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith(`/quizzes/${QUIZ_ID}/attempts/${ATTEMPT_ID}`));
  });

  it("GF2-16 a perfect score has no retry button", async () => {
    base().on(ATTEMPT, () => json(200, submitted)).on(QUIZ, () => json(200, quiz())).on(RESULTS, () => json(200, results({ score: 3, percent: 100 })));
    openReview();
    await screen.findByRole("heading", { level: 2, name: "3 of 3 correct" });
    expect(screen.queryByRole("button", { name: "Retry wrong answers" })).toBeNull();
  });
});

describe("GF2-20 not found without leaks", () => {
  it("GF2-20 malformed ids are not requested; missing and foreign ids and an attempt of another quiz show the same state", async () => {
    const texts: string[] = [];
    const cases: { open: () => { unmount: () => void }; setup: () => ReturnType<typeof base>; malformed: boolean }[] = [
      { open: () => openQuiz("not-an-id"), setup: () => base(), malformed: true },
      { open: () => openQuiz(), setup: () => base().on(QUIZ, () => problem(404, "not_found", "Resource not found.")), malformed: false },
      { open: () => openAttempt(QUIZ_ID, "../../x"), setup: () => base(), malformed: true },
      {
        open: () => openAttempt(),
        setup: () => base().on(QUIZ, () => json(200, quiz())).on(ATTEMPT, () => json(200, attempt({ quiz_id: OTHER_ID, questions: [{ ...attempt().questions![0]!, stem: "Secret stem" }] }))),
        malformed: false,
      },
      { open: () => openReview(), setup: () => base().on(ATTEMPT, () => problem(404, "not_found", "Resource not found.")), malformed: false },
    ];
    for (const { open, setup, malformed } of cases) {
      const b = setup();
      const view = open();
      expect(await screen.findByRole("heading", { level: 1, name: "Not found" })).toBeVisible();
      texts.push(screen.getByRole("main").textContent ?? "");
      expect(document.body.textContent).not.toMatch(/Secret|Practice quiz/);
      if (malformed) expect(b.calls.filter((c) => c.path.startsWith("/quizzes/") || c.path.startsWith("/attempts/"))).toEqual([]);
      view.unmount();
    }
    expect(new Set(texts).size).toBe(1);
  });
});

describe("GF2-21 cache isolation", () => {
  it("GF2-21 signing out clears every quiz, attempt and result query", async () => {
    const b = takingBackend().on("POST /auth/logout", () => new Response(null, { status: 204 }));
    const { queryClient } = openAttempt();
    await screen.findByRole("navigation", { name: "Questions" });
    queryClient.setQueryData(["attempt-results", "x"], results());
    nav.live = false;
    await userEvent.click(screen.getAllByRole("button", { name: /^Account: Test Student/ })[0]!);
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(b.count("POST /auth/logout")).toBe(1));
    await waitFor(() =>
      expect(queryClient.getQueryCache().getAll().filter((q) => ["quiz", "quizzes", "attempt", "attempts", "attempt-results"].includes(String(q.queryKey[0])) && q.state.data !== undefined)).toEqual([]),
    );
  });
});

describe("GF2-22 GF2-23 GF2-24 F-M4-03 — Frontend Rendering Safety / F-M3-03 — Prompt Injection Residual in quizzes", () => {
  it("GF2-22 GF2-23 hostile titles, stems, options, rationales, evidence and topics stay inert text and cause no action", async () => {
    const hostile = HOSTILE_AI.join(" ");
    const questions = [{ ...attempt().questions![0]!, stem: hostile, options: [...HOSTILE_AI.slice(0, 4)] }];
    const b = base()
      .on(QUIZ, () => json(200, quiz({ title: HOSTILE_AI[2], notice: HOSTILE_AI[5], questions })))
      .on(ATTEMPT, () => json(200, attempt({ questions })));
    const view = openAttempt();
    expect(await screen.findByRole("heading", { level: 2, name: hostile })).toBeVisible();
    const check = () => {
      expect(document.querySelector("main script, main img, main iframe")).toBeNull();
      expect([...document.querySelectorAll("a")].map((a) => a.getAttribute("href") ?? "").filter((h) => !h.startsWith("/") && h !== "#main")).toEqual([]);
      expect(b.calls.filter((c) => c.method === "DELETE")).toEqual([]);
    };
    check();
    view.unmount();
    base()
      .on(ATTEMPT, () => json(200, attempt({ status: "submitted", questions: null, answers: null, score: 0 })))
      .on(QUIZ, () => json(200, quiz({ title: HOSTILE_AI[2] })))
      .on(RESULTS, () =>
        json(200, results({ topics: [{ topic: HOSTILE_AI[0], score: 0, max_score: 1 }], questions: [{ ...results().questions[0]!, stem: hostile, options: [...HOSTILE_AI.slice(0, 4)], rationale: hostile, rationale_chosen: HOSTILE_AI[7], evidence: hostile, citation: { document_id: "d", file_name: HOSTILE_AI[1], citation_label: HOSTILE_AI[3], page: 1, slide: null } }] })),
      );
    openReview();
    expect((await screen.findAllByText(new RegExp(HOSTILE_AI[5].replace(/\./g, "\\.")))).length).toBeGreaterThan(1);
    check();
  });

  it("GF2-24 long stems, options and evidence wrap", async () => {
    const long = "x".repeat(2500);
    takingBackend(attempt({ questions: [{ ...attempt().questions![0]!, stem: long, options: [long, "b", "c", "d"] }] }));
    openAttempt();
    const heading = await screen.findByRole("heading", { level: 2, name: long });
    expect(heading.className).toContain("break-words");
    expect(screen.getAllByText(long).find((el) => el.tagName === "SPAN")!.className).toContain("break-words");
  });
});

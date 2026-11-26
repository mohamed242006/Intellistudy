# F2 Gate: Quiz Generation, Attempts and Results

**Scope:** milestone F2 of [`FRONTEND_IMPLEMENTATION_PLAN.md`](FRONTEND_IMPLEMENTATION_PLAN.md):
- course quizzes (list, generate, status, regenerate, delete);
- quiz taking (start or resume, answer multiple-choice and true/false questions, navigation, submission);
- results and review, and "Retry wrong answers".

It builds on F0-A, F0-B and F1 ([`F0A_GATE.md`](F0A_GATE.md), [`F0B_GATE.md`](F0B_GATE.md), [`F1_GATE.md`](F1_GATE.md)).

**Out of scope:**
- short-answer questions and personalised or adaptive exams (team decisions T-5, T-6; the backend has neither);
- immediate per-question feedback, which the backend forbids before submission (ISO-04, G5-KEY-02);
- MasteryRing and mastery levels (thresholds are an open question, UI §18 D-20; mastery is F5);
- generated advice text ("Strong on pointcuts…");
- timers, "Open in file" (no document viewer), quiz analytics, final mobile layouts (F3), Settings (F4).

**Version:** 1.0, 2026-11-26, written before implementation. Section 23 holds the evidence.

**Sources, in priority order:**
1. Backend code and OpenAPI:
   - `backend/app/api/v1/generation.py` (quizzes) and `attempts.py`;
   - `services/generation.py`, `quizgen.py`, `attempts.py`, `lifecycle.py`, `retrieval.py`;
   - `core/ratelimit.py`, `db/models.py`.
2. The security contract and the M4 and M5 release gates.
3. Figma (UI §7.19, §8.7, §8.8).
4. The plan.

Every contract row below was read in code and confirmed against an isolated backend with the deterministic test
provider (2026-11-26).

## 1. Scope

| Area | Delivered |
|---|---|
| Entry points | Workspace title row "Quizzes"; file details "Generate quiz" (prefills that file); course quizzes page |
| Generation | form with title, question count, question types, source files (backend fields only); async lifecycle with polling |
| Quiz page | status (generating, ready, failed, invalid), notice, Start or Continue, Regenerate, Delete, attempt history |
| Taking | one question per screen, question navigator, save on selection, Previous / Skip / Next, Finish with confirmation |
| Results | backend score, percent, topic scores, every question with the backend's correctness, correct answer, rationale, evidence and citation; Retry wrong answers |

## 2. Out of scope

See the scope note above. Nothing in F2 shows a score, correctness, correct answer, rationale, evidence or citation
that the backend has not returned for a **submitted** attempt.

## 3. Verified backend contract

| Endpoint | Request | Success | Failures |
|---|---|---|---|
| `POST /courses/{id}/quizzes` | `{document_ids? (1-20 ready ids of this course), question_count (5-30, default 10), question_types (mcq, true_false; 1-2; default both), title? (≤200, trimmed)}` | **202** `QuizOut` with `status: generating` (always a **new** quiz) | 404 (course, or any document id that is foreign, of another course, not ready or malformed), 409 `document_not_ready` (no ready document), 422 `too_many_documents`, 422 `validation_error`, 503 `llm_unavailable`, 429 `rate_limited` (`quiz:user` 5 per hour, `Retry-After`), 429 `token_budget` |
| `GET /courses/{id}/quizzes` | `limit` 1-100 (50), `offset` | `{items: QuizOut[], limit, offset}`, newest first, no total | 404 |
| `GET /quizzes/{id}` | | `QuizDetail` = `QuizOut` + `questions` (**public fields only**; empty unless `ready`) | 404 |
| `POST /quizzes/{id}/regenerate` | none | **202** `QuizOut` (`generating`); an active job is reused; in-progress attempts expire; submitted attempts are kept | 404, 409 `document_not_ready`, 503, 429 |
| `DELETE /quizzes/{id}` | | 204 (attempts and results deleted too) | 404 |
| `POST /quizzes/{id}/attempts` | **no body** (any body: 422 `unexpected_body`) | **201** new attempt, or **200** the attempt already in progress (resume) | 404, 409 `quiz_not_ready`, 429 (`attempt:start` 30 per hour) |
| `GET /quizzes/{id}/attempts` | `limit`, `offset` | `{items: AttemptOut[]}`, newest first | 404 |
| `GET /attempts/{id}` | | `AttemptDetail`: `questions` and `answers` **only while in progress** (null otherwise) | 404 |
| `PUT /attempts/{id}/answers/{questionId}` | `{choice: 0-3}` (mcq) **or** `{value: bool}` (true/false), exactly one | 200 `SavedAnswer{question_id, answer{choice, value}, saved_at}` (upsert; changeable until submitted) | 404 (attempt or question not in it), 409 `attempt_submitted` / `attempt_expired`, 422 `invalid_answer` / `validation_error`, 429 (`attempt:answer` 600 per hour) |
| `POST /attempts/{id}/submit` | no body | 200 `AttemptResults`; **idempotent** (a submitted attempt returns its stored snapshot) | 409 `attempt_expired`, 409 `quiz_not_ready`, 429 (`attempt:submit` 30 per hour), 404 |
| `GET /attempts/{id}/results` | | 200 `AttemptResults` | 409 `attempt_not_submitted` / `attempt_expired`, 404 |
| `POST /attempts/{id}/retry-missed` | no body | **201** `AttemptDetail` with only the missed questions, `parent_attempt_id` set | 409 `nothing_to_retry`, `quiz_changed`, `attempt_in_progress`, `attempt_submitted`/`not_submitted`, 404, 429 |

## 4. Quiz-generation lifecycle

```
POST → generating ──(job)──► ready (question_count ≥ 5; notice when fewer than requested)
                   └──────► failed (error_code: insufficient_material | llm_unavailable | token_budget | internal_error)
ready ── source document deleted ──► invalid (invalid_reason: source_deleted, notice) ── regenerate ──► generating
ready/failed/invalid ── regenerate ──► generating (questions cleared; in-progress attempts expire)
```

- **Asynchronous.** The client polls `GET /quizzes/{id}` every 2 s while `status` is `generating`, using the F0-B
  rules: paused while the tab is hidden, backoff, stops after 5 failed polls with "Try again", stops on unmount.
- **List page:** the course list polls only while one of its quizzes is `generating`.
- **No resubmission:** `POST` always creates a new quiz, so the form blocks double submission and never retries.
- **Backend validation decides the questions** (QAV-01..08: structure, quoted evidence, support, single answer,
  near-duplicates, server-side option shuffling). The client never sees a key.

## 5. Quiz and question schemas

- **`QuizOut`:** `id, course_id, title, status (generating|ready|failed|invalid), invalid_reason, error_code, notice,
  requested_count, question_count, question_types[], source_document_ids[], model, generated_at, created_at`.
- **`QuestionOut`** (public): `id, position, type (mcq|true_false), stem, options (4 strings for mcq, null for
  true_false), topic, difficulty, cognitive_level`. **No key, rationale, evidence or source.**

Not displayed: `model` (internal), `cognitive_level` and `difficulty` (not in Figma; no approved use).

## 6. Attempt lifecycle

```
start (201 new | 200 resume) ─► in_progress ── PUT answer (any number, changeable) ──► in_progress
in_progress ── submit ──► submitted (graded once, snapshot stored; submit again = same snapshot)
in_progress ── quiz regenerated ──► expired (expired_reason: quiz_regenerated; cannot be answered or submitted)
submitted ── retry-missed ──► new in_progress attempt (parent_attempt_id) with only the missed questions
```

- At most one attempt in progress per quiz (D5-2).
- Navigation order is the attempt's fixed `question_ids` order (positions 1..N).
- An unanswered question is graded incorrect; there is no "clear answer" endpoint.

## 7. Question types and payloads

| Type | Control | Payload | Empty | Review |
|---|---|---|---|---|
| `mcq` | radio group of the 4 `options` | `{choice: index}` (index in the shuffled `options` the server sent) | no answer row | your option and the correct option marked with words |
| `true_false` | radio group "True" / "False" | `{value: true \| false}` | no answer row | your value and the correct value marked with words |

An unknown future `type` renders as "This question type isn't supported here" with no input, and is never answered.

## 8. Decisions and conflicts

| Topic | Decision |
|---|---|
| "Check answer" (Figma) vs answer secrecy (backend) | plan 11.2: the label would mislead. An answer is **saved when chosen** (PUT); the primary button is "Next question" (provisional), "Skip question" moves on without answering, "Previous" goes back. Correctness appears only in Review |
| Save timing | save on selection, serialised per question (a newer choice waits for the earlier request, then is sent; the last choice wins); status per question "Saving…" / "Saved" / "Not saved: …" with Try again |
| Navigation | a question navigator (not drawn; provisional): one button per question named "Question n, answered / not answered", `aria-current="step"` on the current one |
| Finish | "Finish quiz" on the last question (and in the navigator) opens a confirmation stating the real number of unanswered questions; submit only on "Submit answers" |
| Exit | "Exit quiz" returns to the quiz page; answers are already saved. If a save is pending or failed, a confirmation is shown first |
| Short answer, "Partly correct", draft counter | not supported by the backend: not built |
| Result summary | "n of N correct" (h2) and `percent` from the backend; topic scores from `topics[]`. No MasteryRing, no level word, no generated advice (D-20 open; F5) |
| Review | one question expanded at a time (D-12): the first incorrect one opens first; Tags "Correct" / "Incorrect" / "Not answered" (text + tone); AnswerOption Correct/Incorrect states with words; "WHY" = `rationale`, "About your answer" = `rationale_chosen`, both labelled as AI-written; "EVIDENCE" = `evidence` quote in a SourceCard with the `citation` file and location |
| Citations in results | the backend returns **one** `citation` object and an `evidence` quote per question, not `[n]` markers. No badge or source panel is built; nothing is numbered on the client |
| Retry wrong answers | `retry-missed` → the new attempt. Hidden when the score is full. `attempt_in_progress` offers "Continue the attempt in progress" (POST start returns it) |
| Course tabs | still not rendered (F1 decision): entry through the Workspace "Quizzes" button and "Generate quiz" |
| Narrow screens | single column, navigator wraps; provisional for F3 |

## 9. Ownership and non-disclosure

- **Same 404 for all:** missing, malformed and foreign quiz, attempt, course and document ids return the same 404.
- **The UI:**
  - shows one generic not-found state;
  - checks that a quiz belongs to the route's course, and an attempt to the route's quiz;
  - otherwise shows the same not-found state, revealing no title, status, question, answer or score.
- **Malformed route ids** are not requested at all.

## 10. Answer secrecy before submission

- **Endpoints:** before submission the UI calls only the public endpoints (quiz detail, attempt detail, saved
  answers). It never calls `/results` for an in-progress attempt.
- **Display:** it shows no correctness, score, key, rationale, evidence or citation. "Saved" is the only feedback.
- **Cache:** the results key is filled only from a submit response or from `/results` of a submitted attempt.
- **Tests:** they assert the taking page contains none of the result fields or verdict words.

## 11. Results and review rules

- **Source of results:** score, percent, topics and every question's state come only from `AttemptResults`. The client
  never computes or adjusts a score.
- **Correctness:** `correct: true` → "Correct"; `correct: false` and `answered: false` → "Not answered" (graded
  incorrect, as the backend did); `correct: false` → "Incorrect".
- **Unknown values:** an unknown answer shape is shown without a verdict claim.

## 12. Query keys

| Key | Filled by | Invalidated by |
|---|---|---|
| `["quizzes", courseId, {limit}]` | list | create, regenerate, delete (that course only) |
| `["quiz", quizId]` | detail, create/regenerate response | regenerate, delete (removed) |
| `["attempts", quizId, {limit}]` | history | start, submit, retry, regenerate, delete |
| `["attempt", attemptId]` | start/retry response, detail | save (patched in place), submit |
| `["attempt-results", attemptId]` | submit response, results | never before submission |

Logout clears the whole cache (GF0A-12).

## 13. Error handling

- **Fixed copy:** every code in section 3 maps to fixed sentences; problem bodies are never shown.
- **Retry-After:** 429 with `Retry-After` disables only the affected action (generate, start, save, submit, retry)
  until it passes.
- **No automatic retry:** mutations are never retried automatically.
- **Session expiry:** follows F0 (one refresh, one retry, then sign-in).

## 14. Accessibility

- **Structure:** landmarks and headings; each question is a `fieldset` whose `legend` is the stem; options are native
  radio inputs (arrow keys work).
- **Feedback:**
  - the save status is a polite live region per question;
  - generation and submission status are announced;
  - the review uses words for every verdict.
- **Interaction:** the navigator marks the current question programmatically; focus moves to the question heading
  when the question changes; dialogs follow GF0B-03; targets are at least 44×44.
- **axe:** zero serious or critical violations on the quiz list, generation form, quiz page, taking page, submit
  dialog and review.
- **Not covered:** a real screen-reader audit is not claimed.

## 15. Responsive

No horizontal page overflow at 1440×900, 1024×768, 720×900 and 390×844 on the quiz list, taking and review pages.
The quiz column is 720 wide as drawn and shrinks below that. Narrow layouts are provisional (F3).

## 16. Rendering safety and prompt injection

- **F-M4-03 — Frontend Rendering Safety:** quiz titles, stems, options, topics, rationales, evidence, file names and
  notices render as inert React text. No HTML, Markdown, links or `eval`.
- **F-M3-03 — Prompt Injection Residual:** a document's injected instructions can reach a question stem, because the
  backend accepts stems that are supported by evidence. In the UI they stay text and trigger no navigation, request
  or action. The E2E quiz fixture carries such text.
- **Residual:** the frontend contains this at the rendering boundary only.

## 17. Deterministic provider vs real provider

- **Default suite:** the DETERMINISTIC TEST PROVIDER (`tests/e2e/fixtures/stub_llm.py`) also answers quiz prompts.
  - It writes one question per distinct source sentence: multiple choice from the sentence's unique word, or
    true/false, with every fourth statement made false by swapping its keyword.
  - The evidence is the sentence copied word for word.
  - The backend's real validation keeps or drops each question (one is dropped in the probe run), then shuffles the
    options. Grading, scoring, snapshots, retry and ownership are all real backend code.
- **No real model:** no automated test calls DeepSeek or any real model.

## 18. Isolated E2E requirements

- **Harness:** F1's harness: explicit ports 8100/8101/3100, the guard scripts, a temporary database and storage, and
  the offline models with the preflight (the quiz path needs no other model).
- **Fixtures:** `quiz-notes.pdf` (eight distinct facts, the last with injection text), generated per run; never
  `data/uploads`.
- **Accounts:** the run's registered accounts (`tests/e2e/accounts.ts`), within the real rate limits.

## 19. CI requirements

The frontend workflow keeps every F0/F1 check. F2 needs no new model, secret or step. The traceability test checks the
GF2 items.

## 20. Known limitations and blockers

| Item | Detail |
|---|---|
| Icons | still not exported: AnswerOption verdict icons, the radio indicator uses the native control, quiz bar icons |
| MasteryRing | not built (levels undecided, F5) |
| Provisional copy | "Next question", the navigator, the save status, the submit confirmation, error sentences (`features/quiz/strings.ts`) |
| Not drawn in Figma | quiz list, generation form, generating/failed/invalid states, navigator, submit dialog, attempt history |
| Narrow screens | functional only (F3) |
| Backend blockers | none |

## 21. Gate items

| ID | Item | Expected result | Test |
|---|---|---|---|
| GF2-01 | Entry points | Workspace "Quizzes" and file-details "Generate quiz" (with that file preselected) lead to the course quizzes page | unit + E2E |
| GF2-02 | Quiz list | backend quizzes, newest first, pages of 50 with "Show more"; status as text; empty, loading and error states; no invented counts | unit + E2E |
| GF2-03 | Generation form | title ≤200, question count 5-30, types (at least one), ready source files (1-20, all by default); client validation mirrors the backend; non-ready files cannot be chosen | unit + E2E |
| GF2-04 | Generation request | one POST per submission (double submit blocked), never retried; 202 response cached; goes to the quiz page | unit + E2E |
| GF2-05 | Generation lifecycle | generating (polled every 2 s, paused hidden, backoff, stop after failures with Try again, stop on unmount), ready, failed (`error_code` mapped), invalid (notice), "fewer than requested" notice | unit + E2E |
| GF2-06 | Regenerate and delete | confirmations; regenerate warns that an attempt in progress ends; delete returns to the list; caches updated | unit |
| GF2-07 | Start and resume | "Start quiz" (201) or "Continue quiz" (200 resume, saved answers restored); `quiz_not_ready` handled | unit + E2E |
| GF2-08 | Question rendering | one question per screen; `fieldset`/`legend`; mcq four radios; true_false "True"/"False"; unknown types inert | unit + E2E |
| GF2-09 | Answer saving | PUT on selection with the exact payload; serialised per question, last choice wins; Saving / Saved / Not saved + Try again; nothing reported saved before 200 | unit + E2E |
| GF2-10 | Navigation | Previous, Skip, Next, navigator with answered / not answered / current in text and `aria-current`; focus to the question heading; "Question n of N" and progress bar | unit + E2E |
| GF2-11 | Answer secrecy | no result field, verdict or `/results` call before submission; taking-page DOM free of keys and rationales | unit + E2E |
| GF2-12 | Submission | confirmation with the real unanswered count; one POST; duplicate clicks ignored; results cached from the response; then review | unit + E2E |
| GF2-13 | Resume after reload | reload or leave and return: saved answers come back from the server | E2E |
| GF2-14 | Results | backend score, `n of N correct`, percent, topic scores; no client scoring | unit + E2E |
| GF2-15 | Review | per-question Correct / Incorrect / Not answered (words + tone); your answer and the correct answer; rationale, chosen rationale, evidence and citation; first incorrect expanded; unknown shapes claim nothing | unit + E2E |
| GF2-16 | Retry wrong answers | `retry-missed` → new attempt with only the missed questions; hidden on a full score; `attempt_in_progress` and `quiz_changed` handled | unit + E2E |
| GF2-17 | Attempt states | expired attempts (quiz regenerated) cannot be answered or submitted; submitted attempts open the review; `attempt_not_submitted` routes to taking | unit |
| GF2-18 | Attempt history | quiz page lists attempts with status in text and the backend score for submitted ones | unit + E2E |
| GF2-19 | Errors and Retry-After | every code in section 3 mapped; 429 disables only that action until `Retry-After`; network and session expiry | unit |
| GF2-20 | Not found without leaks | missing, foreign and malformed quiz and attempt ids, a quiz of another course and an attempt of another quiz show the same not-found state; malformed ids are not requested | unit + E2E |
| GF2-21 | Query keys and cache | keys of section 12; each mutation touches only its resource; changing quiz or attempt shows no stale data; logout clears all F2 data | unit |
| GF2-22 | F-M4-03 — Frontend Rendering Safety | hostile titles, stems, options, rationales, evidence, topics, file names and notices render as inert text | unit + E2E |
| GF2-23 | F-M3-03 — Prompt Injection Residual | injected document text in a generated question stays text; no navigation, request, deletion or dialog | unit + E2E |
| GF2-24 | Long text | long stems, options and evidence wrap; no page overflow | unit + E2E |
| GF2-25 | Accessibility | axe zero serious/critical on list, form, quiz page, taking, submit dialog, review; keyboard-only answering and submission | E2E |
| GF2-26 | Responsive (provisional) | no horizontal overflow at 1440, 1024, 720, 390 on list, taking and review | E2E |
| GF2-27 | Token storage | no token in web storage or `document.cookie` after the F2 flows | E2E |
| GF2-28 | Deterministic quiz provider | the E2E backend generates quizzes with the deterministic test provider through the real validation; no real model; models preflighted | unit (stub/harness checks) + E2E |
| GF2-29 | CI | the frontend workflow keeps every F0/F1 check and runs the F2 E2E | CI run + unit (workflow check) |

## 22. Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| Frontend lead | Frontend Team (until assigned) | | |
| Backend lead / AI pipeline owner | Mohamed Amir Kamal | | |
| Supervisor | Prof. Gamal Ebrahim | | |

F2 is complete only after the local checks pass, the user pushes the commit, and both CI workflows are green.

## 23. Evidence (local, 2026-11-26)

| Check | Result |
|---|---|
| `npm ci` | OK |
| `npm audit --audit-level=high` | 0 vulnerabilities |
| `npm run lint` | 0 problems |
| `npm run typecheck` | 0 errors, also without `next-env.d.ts` |
| `npm test` (Vitest) | 18 files, **219 passed**. Before F2: 182. New: `f2-units` 11, `f2-pages` 24, traceability 2 |
| `npm run build` | OK. Quiz routes 134-141 kB first load |
| `npx playwright test` (isolated backend + deterministic test provider) | **35 passed** (5 F0-A, 11 F0-B, 10 F1, 9 F2), **twice in a row**, about 99 s each including the build; no process or temporary directory left |
| OpenAPI drift | none |
| ruff (backend, AI, tests, E2E fixtures) | clean |
| Backend regression (no backend file changed) | 402 tests OK; the quiz and attempt suites alone (`test_g4_quizzes`, `test_g5_*`): 83 OK |
| Real provider | **not run**; no automated test calls DeepSeek or any real model |
| CI | pending the push |

**Probe of the real contract (isolated backend, before the UI):**
- **Generation:** `POST` 202 → `generating` → `ready` with 6 questions (validation dropped one stub candidate,
  `second_correct_option`).
- **Start:** 201, then 200 on resume; `{}` as a body: 422 `unexpected_body`.
- **Answers:** a PUT upsert; the wrong kind is 422 `invalid_answer`.
- **Results before submission:** 409 `attempt_not_submitted`.
- **Submit:** 200, and 200 again with the same snapshot; saving afterwards: 409 `attempt_submitted`; the submitted
  detail has no questions or answers.
- **Retry missed:** 201 with only the missed questions.
- **Not found:** random and malformed ids: the same 404.

**Not verified here:** a real screen-reader audit, real-model question quality (manual demo only), final mobile
fidelity, and the CI run.

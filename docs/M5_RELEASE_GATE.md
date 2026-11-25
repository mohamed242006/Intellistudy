# M5 Release Gate: Quiz Taking, End-to-End Slice and Security Verification

**Status:** release gate for backend milestone M5 (quiz attempts and automatic grading, the end-to-end vertical slice,
and the release-level security verification of the contract, section 10.7). **Version 1.1, approved 2026-11-25:**
decisions D5-1..D5-10 approved as written; D5-11 (submitted attempts are immutable) added by the team and enforced
through the existing items G5-ATT-07, G5-ATT-08 and G5-RTY-01 (expected results made explicit; goals and item count
unchanged). v1.2 (2026-11-25, during implementation): G5-E2E-05 wording corrected to the approved M3 behaviour:
without a provider, chat answers `refused` / `llm_unavailable` (M3 G3-ST-02, G3-PRV-01), not a 503; summary and quiz
generation return 503 (M4 D-4). Goal unchanged. v1.0: draft.
**M5 cannot be approved, merged or released unless every item below passes.**
**Authority:** [`backend_security_contract.md`](backend_security_contract.md) v1.10 (rule ids such as `ISO-04`), the
requirements in `IntelliStudy_Architecture_Design_v1.1.docx` (FR-EXM, NFR-PER, NFR-AVL), the M4 gate
([`M4_RELEASE_GATE.md`](M4_RELEASE_GATE.md), team decisions T-1..T-6) and the team decisions in section 1.2. If this
gate and the contract disagree, the contract wins and this file is corrected.

---

## 0. Gate rules

1. Every row has exactly one automated test named `test_g5_<area>_<nn>_...` (e.g. `test_g5_ati_01_...`); a
   traceability test keeps rows and tests one to one (as for M1-M4).
2. A row passes only if its test passes **without skips** on the merge commit in CI (all jobs green). No waivers;
   changing an expected result requires a contract or gate change first.
3. "Same 404" and "generic 401" as defined in [`SECURITY_MERGE_GATE.md`](SECURITY_MERGE_GATE.md) section 1.
4. Quiz taking and grading make **no model call** (T-6). Model behaviour appears only in the end-to-end tests (2.9),
   where it is scripted or the real `DeepSeekProvider` over a mocked HTTP transport: deterministic, **no network
   call**. The manual DeepSeek demo run (section 3) is evidence, not a gate row.
5. The M1 (79), M2 (39), M3 (52) and M4 (67) gates and the M4.1 regression tests must still pass.

---

## 1. Scope of M5

### 1.1 In scope

| Area | Endpoints / components |
|---|---|
| Attempts | `POST /api/v1/quizzes/{quiz_id}/attempts` -> 201 (new) or 200 (the in-progress attempt, resumed); `GET /api/v1/quizzes/{quiz_id}/attempts` (own attempts, newest first, `limit`/`offset`); `GET /api/v1/attempts/{attempt_id}` |
| Answers | `PUT /api/v1/attempts/{attempt_id}/answers/{question_id}` with `{"choice": 0-3}` (multiple choice) or `{"value": true/false}` (true/false); saved at once (FR-EXM-05) |
| Grading | `POST /api/v1/attempts/{attempt_id}/submit` -> 200 with the results; `GET /api/v1/attempts/{attempt_id}/results` |
| Retry | `POST /api/v1/attempts/{attempt_id}/retry-missed` -> 201, a new attempt over the questions answered wrongly or left unanswered |
| Data | `quiz_attempts` (owner, quiz, course, status `in_progress` / `submitted` / `expired`, quiz generation number, parent attempt for retries, started / submitted times, score), the attempt's question set, saved answers, and per-question **result snapshots** written at submission |
| Security verification | contract section 10.7: every row of contract 10.1-10.6 mapped to passing tests; route-inventory checks over the whole API; OWASP Top 10 and OWASP Top 10 for LLM Applications checklist; record in `docs/SECURITY_VERIFICATION.md` |
| End-to-end slice | the whole backend flow through the HTTP API in one test per scenario (2.9), plus a demo runbook `docs/DEMO_RUNBOOK.md` for the manual DeepSeek demo |

**Attempt view (in progress):** the quiz's public questions exactly as `GET /quizzes/{id}` shows them (M4
`QuestionOut`: `id`, `position`, `type`, `stem`, `options`, `topic`, `difficulty`, `cognitive_level`) plus the saved
answers. Never the correct answer, a rationale, evidence, a source or any per-answer correctness (ISO-04).

**Results (submitted only, owner only):** `score`, `max_score`, `percent`, `time_spent_seconds`, a score per topic
(FR-EXM-10), and per question: the student's answer (or `unanswered`), the correct answer, `correct` true/false, and
for every question answered wrongly or left unanswered (FR-EXM-09): the evidence quote (validated in M4 as copied from
the source), the citation (document id, file name, page or slide label) and the model's rationale, marked
`explanation_source: "generated"`.

### 1.2 Team decisions (already made)

| # | Decision | Source |
|---|---|---|
| T-5 / T-6 | Question types: multiple choice and true/false only. No short-answer or essay questions, no adaptive exams, no LLM-based grading. | M4 gate, 2026-11-24 |
| Quiz MVP | Multiple choice + true/false, retry incorrect answers, automatic grading, citations. | contract Appendix B, 2026-11-24 |
| Standing | No frontend, adaptive-learning or equation-extraction work in the backend slice. | owner instructions |
| T-1..T-3 | Deleting a document deletes its summaries and its single-source quizzes; a multi-source quiz becomes `invalid` and its questions and keys are deleted. | M4 gate |

### 1.3 Decisions of this gate (approved 2026-11-25)

| # | Proposal | Reason |
|---|---|---|
| D5-1 | **Scope:** take a quiz (start, save answers, resume, submit), automatic grading, results with per-topic score, time spent, correct answers and cited explanations, retry missed questions, list own attempts. **Deferred:** time limits and automatic submission (FR-EXM-06, Should), question flagging (FR-EXM-11, Could), personalised and diagnostic exams (FR-EXM-01..04, -12), mastery, weak-topic detection, recommendations and analytics (FR-WTD, FR-MST, FR-REC, FR-DSH except the attempt list). | Keeps M5 to the Must requirements of quiz taking; adaptive learning is explicitly out of the slice. |
| D5-2 | **One in-progress attempt per user and quiz.** Starting again returns it with its saved answers (resume, FR-EXM-05). After submission a new start creates a new attempt. | Simple resume; no competing drafts. |
| D5-3 | **Attempts bind to one generation of the quiz** (a generation number that `regenerate` increments). Regenerating a quiz marks its in-progress attempts `expired` (`expired_reason: quiz_regenerated`); they can no longer be answered, submitted or graded. Resolves F-M4-04. | Regeneration deletes the questions an in-progress attempt is answering. |
| D5-4 | **Results are a snapshot written at submission** (stem, options, answer, correct answer, evidence, citation, rationale, topic) and are never recomputed. A submitted attempt's results stay readable and unchanged after the quiz is regenerated. | Results must not change or vanish after the fact; regeneration deletes the old keys. |
| D5-5 | **Deletion removes attempts:** deleting a quiz (by the user or by T-2), invalidating it (T-3) or deleting its course deletes **all** its attempts, answers and snapshots, submitted ones included. | Snapshots hold document text; the deletion rules must leave none of a deleted document's text behind (ISO-03). The cost: score history of an invalidated quiz is lost. |
| D5-6 | **Explanations:** the evidence quote and its citation are the authoritative explanation (validated in M4); the model's stored rationale is shown as secondary text marked `generated`. No model call is made to explain or grade. | FR-EXM-09 without an LLM judge (T-6); F-M4-02 says rationales are not validated. |
| D5-7 | Options appear in their stored (server-shuffled, M4 G4-QAV-08) order in every attempt, retries included. | Per-attempt reshuffling adds state for little value in the MVP. |
| D5-8 | Submitting with unanswered questions is allowed; they score 0 and appear as `unanswered` with the correct answer and explanation. | Students must be able to stop; FR-EXM-10 reports the score honestly. |
| D5-9 | **Limits per user:** attempt start and retry 30 / hour, answer saves 600 / hour, submissions 30 / hour (contract 9a gains these rows). | Bounded writes; normal study never comes close. |
| D5-10 | **The demo is API-level:** the end-to-end slice is proven through the HTTP API and the runbook; no frontend is built in M5. | Standing "no frontend" instruction. |
| D5-11 | **Submitted attempts are immutable** (team addition). After submission no route may modify the attempt's answers, score, result snapshot or grading outcome. Submitting again returns the stored results without grading again; retry creates a separate attempt and leaves its parent unchanged; regeneration expires only in-progress attempts. Deletion (D5-5) removes an attempt; it never edits one. | Results are a record of what the student did; contract ISO-11. |

**Fixture:** users A, B (STUDENT) and C (ADMIN), each with a course. A's course has a ready PDF and a ready PPTX
processed through the real M2 pipeline (sandbox), a ready single-source quiz, a ready quiz over both documents, a
`generating` and an `invalid` quiz; questions of both types with correct answers at varied positions (scripted
`QuizModel`); injected deterministic embedder, in-memory vector and parent stores; fake clock; no model call outside
2.9.

---

## 2. Gate items

### 2.1 Attempt ownership isolation

| ID | Test case | Expected result | Rules |
|---|---|---|---|
| G5-ATI-01 | B calls every attempt route on A's quiz and A's attempt: start, list, get, save answer, submit, results, retry-missed | Same 404 for each; security event; A's attempt, answers and results unchanged; nothing created for B | ISO-01, OWN-03, I-13 |
| G5-ATI-02 | Admin C calls the same routes | Same 404 (administrators cannot read or take students' quizzes) | ISO-01, OWN-03 |
| G5-ATI-03 | Random UUIDs and malformed ids for `quiz_id`, `attempt_id` and `question_id` on every attempt route | Same 404 | OWN-04, I-14 |
| G5-ATI-04 | B saves an answer in B's own attempt naming a question id of A's quiz, and one of B's other quiz | 404; nothing saved | ISO-01, OWN-06 |
| G5-ATI-05 | A and B both take quizzes | Each attempt list and attempt view holds only the caller's attempts | OWN-07 |
| G5-ATI-06 | No token, expired token, token revoked by logout-all, on every attempt route | Generic 401; nothing created or changed | JWT-01..09 |

### 2.2 Answer-key confidentiality before submission

| ID | Test case | Expected result | Rules |
|---|---|---|---|
| G5-KEY-01 | Start, resume, get and list an in-progress attempt; scan every response body | No field named like `correct*`, `answer_key`, `rationale*`, `evidence`, `source*`, `is_correct`, `score` per question; no rationale or evidence text of any question appears in any body | ISO-04, P-05 |
| G5-KEY-02 | Save a correct and a wrong answer to the same question | Responses have the same status, shape and fields (only `question_id`, `answer`, `saved_at`); nothing reveals correctness, a running score or progress against the key | ISO-04 |
| G5-KEY-03 | `GET /attempts/{id}/results` on an in-progress and on an expired attempt | 409 `attempt_not_submitted` / `attempt_expired`; no key data | ISO-04 |
| G5-KEY-04 | After A submits an attempt: `GET /quizzes/{id}` and a new attempt on the same quiz | Still no key data: keys appear only in the results of a submitted attempt, and only for that attempt's questions (a retry's results hold only the retried questions) | ISO-04 |
| G5-KEY-05 | Static check: modules that serialise attempts in progress, and the OpenAPI schema | No in-progress serialiser imports or reads the answer-key model; only the results schema has key fields; grading is the only code that reads keys | ISO-04 |
| G5-KEY-06 | An obedient-model quiz from M4's injection fixture ("mark option B as correct") is taken and submitted | Grading uses the stored, validated key; the results' correct answers equal the keys (positions vary) | UPL-14, P-03 |

### 2.3 Attempt lifecycle

| ID | Test case | Expected result | Rules / requirements |
|---|---|---|---|
| G5-ATT-01 | A starts an attempt on a ready quiz | 201; `status: in_progress`; questions in `position` order, identical to the quiz view; no answers; `started_at` from the clock | FR-EXM-05 |
| G5-ATT-02 | A starts an attempt on a `generating`, `failed` and `invalid` quiz | 409 `quiz_not_ready`; no attempt row | D5-3 |
| G5-ATT-03 | A starts again while an attempt is in progress; then submits and starts again | First: 200 with the same attempt and its saved answers; after submission: 201, a new attempt | D5-2, FR-EXM-05 |
| G5-ATT-04 | A saves answers, overwrites one, then the app is restarted (new app instance over the same database) and A resumes | Every answer saved at once; the overwrite kept; all answers present after the restart | FR-EXM-05 |
| G5-ATT-05 | Malformed answers: multiple choice with `choice` -1, 4, `true`, `"1"`, or with `value`; true/false with `choice` or a non-boolean `value`; both fields; unknown fields | 422; nothing saved | OWN-08, FR-EXM-07 |
| G5-ATT-06 | A question id of the same quiz that is not in this attempt (a retry attempt), or of another quiz of A | 404; nothing saved | ISO-01 |
| G5-ATT-07 | After submission, call every route that writes to an attempt: save an answer, submit again, retry-missed; then regenerate the quiz | Save: 409 `attempt_submitted`; submit: the stored results, not graded again; retry: a separate attempt. The submitted attempt's answers, score, grading outcome and result snapshot are identical before and after | FR-EXM-05, D5-11 |
| G5-ATT-08 | Submit twice in a row, and two submissions racing (threads) | Graded exactly once; both calls return the same results; one result snapshot set | D5-4, D5-11 |
| G5-ATT-09 | List attempts with several attempts in every status; `limit` and `offset` | Own attempts of that quiz only, newest first; `score` shown only for submitted ones; bounds as in M3/M4 lists | FR-DSH-05, OWN-07 |
| G5-ATT-10 | `GET /attempts/{id}` for in-progress, submitted and expired attempts | In progress: questions and answers (2.2 rules); submitted: status, score and times (details at `/results`); expired: status and reason only | FR-EXM-05 |

### 2.4 Grading and results

| ID | Test case | Expected result | Rules / requirements |
|---|---|---|---|
| G5-GRD-01 | Multiple-choice answers, right and wrong, with the correct option at each of the four positions | 1 point when the chosen index equals the stored key for the displayed order, else 0 | FR-EXM-07, D5-7 |
| G5-GRD-02 | True/false answers, right and wrong, for `true` and `false` keys | 1 / 0 accordingly | FR-EXM-07 |
| G5-GRD-03 | Submit with unanswered questions | Allowed; each scores 0, is listed `unanswered`, with the correct answer and explanation | D5-8 |
| G5-GRD-04 | Totals on a mixed attempt | `score`, `max_score`, `percent`; per-topic scores grouped by the question's topic (case and spacing normalised); `time_spent_seconds` = submission time - start time from the fake clock | FR-EXM-10 |
| G5-GRD-05 | Every question answered wrongly or unanswered | Correct answer; evidence quote equal to the stored key's evidence; citation (document id, file name, page or slide) pointing at the question's own source chunk in A's document; rationale marked `generated` | FR-EXM-09, D5-6 |
| G5-GRD-06 | Spy on the model provider and the usage ledger through start, save, submit, results and retry; repeat with no provider configured and with the daily token budget exhausted | No model call, no ledger row; every attempt route works in both states | T-6, NFR-AVL-03 |
| G5-GRD-07 | Timing in-process on the test client: 100 answer saves; submit and results of a 30-question attempt | Save p95 under 300 ms; submit and results each under 1 s | NFR-PER-01, NFR-PER-06 |
| G5-GRD-08 | Read a submitted attempt's results, then regenerate the quiz and read them again | Identical results (snapshot); the regeneration's new keys do not change them | D5-4, F-M4-04 |

### 2.5 Retry missed questions

| ID | Test case | Expected result | Rules / requirements |
|---|---|---|---|
| G5-RTY-01 | Retry a submitted attempt with k questions wrong or unanswered | 201; a new attempt over exactly those k questions in their original order; `parent_attempt_id` set; the parent attempt's answers, score and results unchanged | Quiz MVP, D5-11 |
| G5-RTY-02 | Retry an attempt with every question correct | 409 `nothing_to_retry`; no attempt | Quiz MVP |
| G5-RTY-03 | Retry an in-progress or expired attempt | 409 `attempt_not_submitted` / `attempt_expired` | D5-3 |
| G5-RTY-04 | Retry after the quiz was regenerated since the attempt | 409 `quiz_changed`; no attempt | D5-3 |
| G5-RTY-05 | Retry while another attempt on the quiz is in progress | 409 `attempt_in_progress` naming that attempt's id; nothing created | D5-2 |
| G5-RTY-06 | Submit a retry attempt | Graded on its k questions only (`max_score` = k); its results hold keys for those questions only | ISO-04 |

### 2.6 Quiz changes and deletion (F-M4-04, T-1..T-3)

| ID | Test case | Expected result | Rules |
|---|---|---|---|
| G5-LIF-01 | Regenerate a quiz with an in-progress attempt | The attempt becomes `expired` / `quiz_regenerated`; saving and submitting return 409 `attempt_expired`; its answers are kept but never graded | D5-3 |
| G5-LIF-02 | Start an attempt while the quiz is regenerating | 409 `quiz_not_ready` | D5-3 |
| G5-LIF-03 | Delete the only source document of a quiz with in-progress and submitted attempts (T-2) | Quiz, attempts, answers and result snapshots all deleted; the attempt ids return the same 404 | D5-5, ISO-03 |
| G5-LIF-04 | Delete one of two source documents (T-3) | Quiz `invalid`; all its attempts, answers and snapshots deleted, submitted ones included; no text of the deleted document remains in any attempt table | D5-5, ISO-03 |
| G5-LIF-05 | `DELETE /quizzes/{id}`; then delete the course of another quiz with attempts | All attempts, answers and snapshots of those quizzes gone; other quizzes' attempts untouched | D5-5, ISO-03, FR-CRS-03 |
| G5-LIF-06 | A source document is marked `deleting` (purge not finished) while A submits | 409 `quiz_not_ready`; no snapshot written; the purge then removes the attempt | ISO-03, RET-05 |
| G5-LIF-07 | Any of the deletions above | The usage ledger is unchanged (no refund, no new row) | UPL-16 |

### 2.7 Limits and input validation

| ID | Test case | Expected result | Rules |
|---|---|---|---|
| G5-ABU-01 | Exceed each M5 limit: starts and retries (31 / hour), answer saves (601 / hour), submissions (31 / hour) | 429 with `Retry-After`; security event; another user unaffected | D5-9, 9a, SEC-09 |
| G5-ABU-02 | Request bodies with `owner_id`, `user_id`, `quiz_id`, `course_id`, `score`, `correct`, `started_at`, `status` | 422; nothing changed (a client cannot set its own score, key or time) | OWN-08, I-15 |
| G5-ABU-03 | `submit` and `retry-missed` with any body | 422 (they take none); nothing graded from client input | OWN-08 |
| G5-ABU-04 | Oversized answer body | 413 / 422 before any write | HTTP-06 |
| G5-ABU-05 | Attempt list with `limit` 0 or 101, negative `offset` | 422 | OWN-07 |

### 2.8 Security release verification (contract 10.7)

| ID | Test case | Expected result | Rules |
|---|---|---|---|
| G5-SEC-01 | Parse contract sections 10.1-10.6 and `docs/SECURITY_VERIFICATION.md` | Every contract row (I-, R-, A-, U-, P-, S-) is listed with at least one test; every listed test exists in the repository and is collected by the suites | 10.7 |
| G5-SEC-02 | Route inventory from the app's OpenAPI | Every route except an explicit allowlist (`/health`, `register`, `login`, `refresh`, `logout`) answers a request without a token with the generic 401; a new route without auth fails the test | JWT-01, OWN-02 |
| G5-SEC-03 | Every route with an id path parameter, enumerated from the app | A random UUID and a malformed id give the same 404 for an authenticated user; a route missing from the test's id map fails the test | OWN-04, I-14 |
| G5-SEC-04 | Every route with an id path parameter, called by B with A's ids from the full fixture (course, document, conversation, summary, quiz, attempt, question) | Same 404 and a security event for each; a route missing from the map fails the test | ISO-01, OWN-03, I-01..I-13 |
| G5-SEC-05 | Every route's response (success and error) | Security headers present; `Cache-Control: no-store` on user data; errors are RFC 7807 bodies without traces | HTTP-03, HTTP-04, S-07, S-08 |
| G5-SEC-06 | Every request-body model, enumerated from the app | Rejects unknown fields (422) | OWN-08, I-15 |
| G5-SEC-07 | Every response schema in the OpenAPI document | Fields named like `correct*`, `answer_key`, `rationale*`, `evidence` appear only in the attempt results schema | ISO-04 |
| G5-SEC-08 | OWASP Top 10 (2021) and OWASP Top 10 for LLM Applications (2025) checklist in `docs/SECURITY_VERIFICATION.md` | Every item is `pass` with evidence (rule ids, tests), `residual` with a finding id that exists in contract Appendix D, or `n/a` with a reason; no item is `open` | NFR-SEC-06, 10.7 |

### 2.9 End-to-end slice

Each test drives the HTTP API only, with the real M2 pipeline (sandbox), the scripted model (or `DeepSeekProvider`
over a mocked transport) and a fresh database and storage.

| ID | Test case | Expected result | Rules / requirements |
|---|---|---|---|
| G5-E2E-01 | A: register, log in, create a course, upload a PDF and a PPTX, wait for `ready`, ask a cited question, generate a summary and a quiz, take the quiz, submit, read results, retry the missed questions, submit the retry, refresh the token, log out | Every step returns its documented status; citations in chat, summary and results point at A's documents; the logged-out refresh token is rejected | FR-UPL, FR-CHT, FR-SUM, FR-QZ, FR-EXM-05..10 |
| G5-E2E-02 | B runs the same flow at the same time with the **same PDF bytes**; every response body of both users is recorded | No response to B contains an id or document text of A's, and the reverse | ISO-06, ISO-08, R-03 |
| G5-E2E-03 | Then A deletes one document, then the course | T-1..T-3 and D5-5 effects; after the course deletion no row, vector, parent or file of A's course remains in any store; A's ledger rows remain; B's data untouched | ISO-03, UPL-16, FR-CRS-03 |
| G5-E2E-04 | The app is restarted mid-flow: an ingestion job, a quiz generation job and an attempt in progress | The jobs are recovered and finish; the attempt resumes with its saved answers | NFR-REL, FR-EXM-05 |
| G5-E2E-05 | No model provider configured | Chat answers `refused` / `llm_unavailable` (M3); summary and quiz generation return 503 `llm_unavailable`; stored summaries and quizzes are readable; taking, submitting and reading results of an existing quiz work | NFR-AVL-03, D-4 (M4) |

### 2.10 Evidence (local, 2026-11-25)

| Area | Tests | File | Result |
|---|---|---|---|
| 2.1 Attempt ownership isolation | G5-ATI-01..06 | `backend/tests/test_g5_attempts.py` | pass |
| 2.2 Answer-key confidentiality | G5-KEY-01..06 | `backend/tests/test_g5_attempts.py` | pass |
| 2.3 Attempt lifecycle | G5-ATT-01..10 | `backend/tests/test_g5_attempts.py` | pass |
| 2.4 Grading and results | G5-GRD-01..08 | `backend/tests/test_g5_grading.py` | pass |
| 2.5 Retry missed questions | G5-RTY-01..06 | `backend/tests/test_g5_grading.py` | pass |
| 2.6 Quiz changes and deletion | G5-LIF-01..07 | `backend/tests/test_g5_lifecycle.py` | pass |
| 2.7 Limits and input validation | G5-ABU-01..05 | `backend/tests/test_g5_lifecycle.py` | pass |
| 2.8 Security release verification | G5-SEC-01..08 | `backend/tests/test_g5_security.py` | pass |
| 2.9 End-to-end slice | G5-E2E-01..05 | `backend/tests/test_g5_e2e.py` | pass |
| Traceability | 61 rows map one to one to `test_g5_*` | `backend/tests/test_g1_m0.py` | pass |

- Whole suites: backend 402 tests OK, no skips (M1-M4 gates, M4.1 regressions and the ledger tests included);
  `ai/` 800 tests OK (12 skipped, 1 expected failure; unchanged by M5); ruff clean; mypy clean (159 files). A run of
  the `ai/` suite concurrently with the backend suite failed its CPU-timing test
  (`tests/test_performance.py::test_cost_grows_roughly_linearly_with_input_size`); it passes when run alone.
- M4 gate v1.3: G4-INJ-05 and G4-KEY-03 now expect the approved M5 attempt routes and grader (their M4 wording had
  said "in M4"; the exclusions they protect are unchanged).
- Timing (G5-GRD-07, in-process test client): answer save p95, submit and results all well inside 300 ms and 1 s.
- Mutation checks (each control removed, the M5 gate run, the control restored):

| Control removed | Gate tests that fail |
|---|---|
| ownership check on attempts | ATI-01, -02, -03, -05, LIF-03..06, SEC-03, SEC-04, E2E-03 |
| a correctness field on the save response | KEY-01, KEY-02, KEY-05, SEC-07 |
| status guard before saving | LIF-01 |
| conditional claim when saving (a save racing a submission) | ATT-07 (after adding the race case: the status guard alone had masked it) |
| submit returns the stored snapshot (instead of grading again) | ATT-07, ATT-08, ABU-01 |
| expire in-progress attempts on regeneration | ATT-09, ATT-10, KEY-03, LIF-01, RTY-03 |
| delete attempts on invalidation (T-3) | LIF-04, LIF-06, E2E-03 |
| sources still `ready` at submission | LIF-06 |
| retry checks the quiz generation | RTY-04 |
| answer-save rate limit | ABU-01 |
| no body on start, submit and retry | ABU-02, ABU-03 |

- The explicit attempt deletion on T-2 and on quiz deletion is defence in depth: the foreign-key cascade removes the
  attempts too, so removing it alone fails no test (the T-3 path, where the quiz row survives, proves it).
- Findings F-M5-01..03 in the contract's Appendix D (F-M5-01, a stale identity map after the submission claim, fixed
  during implementation).

---

## 3. Sign-off

M5 is approved only when the record that completes it (pull request, or this file while work stays on the branch) shows:

- [x] Team approval of decisions D5-1..D5-10 **before implementation** (2026-11-25, as written, plus D5-11), and the
      contract updated to match (v1.10): 9a (attempt limits), ISO-03 (attempts deleted with their quiz, including on
      invalidation), ISO-04 (keys only in the results snapshot of a submitted attempt), ISO-11 (submitted attempts
      immutable), I-13 (attempt get and list routes); Appendix D F-M4-04 decided (closed when this gate passes).
- [ ] CI run link for the commit, all jobs green (tests, lint and types, dependency audit, secret scan).
- [ ] Every `test_g5_*` test passed, no skips (61 items), plus the traceability test; M1-M4 gates still passing.
- [ ] `docs/SECURITY_VERIFICATION.md` complete: every contract 10.1-10.6 row mapped to passing tests (G5-SEC-01), the
      OWASP checklist without open items (G5-SEC-08), signed by the owner. This is the contract's release gate (10.7).
- [ ] Evidence: one manual demo run with DeepSeek following `docs/DEMO_RUNBOOK.md` on real lecture files (upload to
      results and retry), recorded without document content: processing time (NFR-PER-04), quiz generation time
      (NFR-PER-05), answer-save and grading times (NFR-PER-01, -06), tokens used, quiz yield.
- [ ] Open items recorded with an owner and a deadline, none blocking the demo: F-M4-07 (soft hyphens at ingestion);
      the privacy notice for sending document content to DeepSeek (contract Appendix B, required before any non-team
      user uploads); the shared rate-limiter store before any multi-process deployment (contract 9a).

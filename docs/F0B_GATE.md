# F0-B Gate: Dashboard, Courses, Course Workspace and Document Uploads

**Scope:** milestone F0-B of [`FRONTEND_IMPLEMENTATION_PLAN.md`](FRONTEND_IMPLEMENTATION_PLAN.md):
- the authenticated application shell (Sidebar, Rail);
- the Dashboard, showing backend data only;
- course creation, rename and deletion;
- the Course Workspace;
- the upload flow, with per-file progress;
- polling of processing statuses;
- document retry, download and deletion.

It builds on F0-A ([`F0A_GATE.md`](F0A_GATE.md)), which is unchanged except where noted in section 6.

**Out of scope:** summaries, chat, quizzes, attempts, analytics, mastery, streaks, weakest topics, recommendations,
recent activity, Settings, Data & privacy, data export, account deletion, push, WebSockets or SSE, OCR status, dark
theme controls, and final mobile layouts (F3). No sample data is shown anywhere.

**Version:** 1.0, 2026-11-25, written before implementation. Section 7 holds the evidence.

**Sources, in priority order:**
1. The backend implementation and its OpenAPI schema:
   - `backend/app/api/v1/courses.py`, `documents.py`, `schemas.py`;
   - `services/documents.py`, `uploads.py`, `storage.py`, `ownership.py`, `jobs.py`;
   - `core/errors.py`, `core/config.py`, `core/ratelimit.py`, `db/models.py`.
2. The security contract.
3. Figma ([`figma_ui_context.md`](figma_ui_context.md), cited as "UI §n").
4. The plan.

Every row in section 0 was read in code and then confirmed against a running backend (2026-11-25).

## 0. Verified backend contract (F0-B)

### 0.1 Endpoints

| Endpoint | Request | Success | Failures used by the UI |
|---|---|---|---|
| `POST /courses` | `{name, code?, description?}`; `name` is stripped, then 1-200 characters; unknown fields rejected | 201 `CourseOut{id,name,code,description,archived,created_at,updated_at}` | 422 `validation_error` (`errors[{loc:["body","name"], type:"string_too_short"\|"string_too_long"}]`) |
| `GET /courses` | `limit` 1-100 (default 50), `offset` 0-100000, `include_archived` (default false) | 200 `{items, limit, offset}`. **No total** (G1-ISO-04); ordered newest first | 422 on out-of-range parameters |
| `GET /courses/{id}` | - | 200 `CourseOut` | 404 `not_found`: the same body for missing, foreign and malformed ids (OWN-04) |
| `PATCH /courses/{id}` | any of `name`, `code`, `description`, `archived`; `name` may not be null | 200 `CourseOut` | 404, 422 |
| `DELETE /courses/{id}` | - | 204; every document (vectors, files, summaries, quizzes) is purged first (ISO-03) | 404 |
| `POST /courses/{id}/documents` | multipart, file parts named `files`, at most 10 per request, each at most 100 MB (`max_upload_bytes` = 104,857,600 bytes) | 202 `{documents: UploadedDocument[]}`, each document plus `duplicate` | see 0.3 |
| `GET /courses/{id}/documents` | `limit` 1-100 (default 50), `offset` | 200 `{items: DocumentOut[], limit, offset}`, newest first; documents being deleted are excluded | 404 |
| `GET /documents/{id}` | - | 200 `DocumentOut` | 404 (also while the document is being deleted) |
| `GET /documents/{id}/file` | bearer token | 200: the original file; `Content-Disposition: attachment; filename*=UTF-8''<percent-encoded>`; verified media type; `nosniff`; `Cache-Control: no-store` | 404 |
| `POST /documents/{id}/retry` | - | 202 `DocumentOut` (status `queued`) | 409 `not_failed` (only `failed` documents); 429 `queue_full` |
| `DELETE /documents/{id}` | - | 204 | 404 |

`DocumentOut` has these fields:
- `id`, `course_id`;
- `file_name` (normalised display name, at most 255 characters, no path);
- `file_type` (`pdf` | `docx` | `pptx`);
- `size_bytes`;
- `status`;
- `progress` (0-100, coarse per stage);
- `error_code`;
- `error_message` (a fixed backend sentence);
- `page_count`, `chunk_count`;
- `created_at`, `updated_at`, `ready_at`.

### 0.2 Document statuses (`DocumentStatus`)

- **In progress:** `queued`, `validating`, `extracting`, `chunking`, `embedding`, `indexing`.
- **Terminal:** `ready`, `failed`.
- **`deleting`:** never returned by the list.

Failure codes (`REASONS` in `services/documents.py`): `empty_file`, `unsupported_type`, `type_mismatch`,
`password_protected`, `macro_document`, `archive_rejected`, `too_many_pages`, `corrupted`, `unreadable`, `timed_out`,
`too_large`, `invalid_output`, `no_text`, `internal_error`.

**No OCR signal is exposed.**

### 0.3 Upload rules

- **Validated per request, all or nothing.** One bad file rejects every file in that request, so the UI sends
  **one request per file** to keep outcomes independent.
- **Before any byte is stored:**
  - the course must be the caller's (404 otherwise);
  - capacity: 429 `queue_full` when the user already has 5 active processing jobs (`max_queued_jobs_per_user`).
- **While streaming:**

  | Problem | Response |
  |---|---|
  | Not multipart | 415 `unsupported_media_type` |
  | Unexpected part | 422 `unexpected_field` |
  | More than 10 files | 422 `too_many_files` |
  | A file over 100 MB | 413 `file_too_large` |
  | No file | 422 `no_files` |
  | Malformed body | 400 `malformed_upload` |

- **Content checks:** 422 `upload_rejected`, with `files[{file, reason, message}]`.
  - `reason` is `empty_file`, `unsupported_type` or `type_mismatch`.
  - The extension is checked **and** the magic bytes are checked.
- **Quotas:**
  - 429 `rate_limited` with `Retry-After`: `upload:user` allows 20 files per hour;
  - 429 `queue_full` when active jobs plus new files would exceed 5;
  - 413 `quota_exceeded` above 1 GiB of stored files.
- **Duplicates:** the same content uploaded again to the same course (unless the earlier copy failed) returns the
  existing document with `duplicate: true`.
- **Deeper checks run later, in the sandbox:** macros, encryption, archive safety, page limits, text extraction.
  These end as `failed` with an `error_code`.

### 0.4 Ownership and pagination

- **Ownership:** every id goes through `get_owned`. A missing id, another user's id and a malformed id produce the
  same 404 body, `Resource not found.`
- **Pagination:** limit and offset, with no total. A page is the last one when it holds fewer items than the limit.

## 1. Gate items

Every item has a test. "Unit" = Vitest + Testing Library (integration tests render real pages over a scripted
backend). "E2E" = Playwright against a real backend started for the run, with its worker processing real files.

| ID | Item | Expected result | Test |
|---|---|---|---|
| GF0B-01 | App shell | Sidebar (UI §6.2) on Dashboard and Upload, Rail (UI §6.3) on the Workspace; only destinations that exist are shown (Dashboard, Courses); `aria-current` on the active item; landmarks `nav`, `main`; the user card shows the signed-in user and opens a disclosure with Sign out | unit + E2E |
| GF0B-02 | F0-B components | Card, NavItem, IconButton, Tag, ProgressBar, EmptyState, Modal, Toast, FileUploadRow, Breadcrumb, StatCard, Avatar, UserCard follow UI §7 (sizes, radii, tokens); semantic tokens only; targets at least 44×44 | unit |
| GF0B-03 | Modal accessibility | `role="dialog"`, `aria-modal`, labelled by its title; initial focus inside (Cancel for destructive dialogs); Tab and Shift+Tab trapped; Escape cancels; focus returns to the trigger; background inert; confirming requires an explicit button press | unit + E2E |
| GF0B-04 | Dashboard shows real data only | greeting and date computed on the client from `/auth/me`; "Your courses" from `GET /courses`; course cards show file counts and processing state from `GET /courses/{id}/documents`; **no** recommendation, streak, weakest topics, recent activity, mastery or sample strings | unit + static scan + E2E |
| GF0B-05 | Dashboard states | loading (Card Loading skeletons, `aria-busy`), empty (EmptyState with New course), error (Notice + Try again) | unit |
| GF0B-06 | Course pagination | pages of 50 (backend default); "Show more courses" while the last page was full; never silently truncated | unit |
| GF0B-07 | Course creation | Modal with one field, "Course name"; trims and checks 1-200 characters like the backend; one request per submission (double submit blocked); errors announced; input kept after a failure; invalidates the course list only; goes to the new course's workspace | unit + E2E |
| GF0B-08 | "Upload files" on the Dashboard | no course: opens New course, then goes to its upload page; one course: goes to its upload page; several: a course chooser (radio group) | unit |
| GF0B-09 | `/courses` | redirects to `/#courses` (Dashboard "Your courses"; no Courses frame exists) | unit + E2E |
| GF0B-10 | Course Workspace | loads `GET /courses/{id}` and its documents; breadcrumb; "Files indexed n of m" stat from real documents; Materials list; selected-file details (type, size, pages or slides, uploaded, indexed); `?file=` selects a file; no mastery, topics or OCR notice | unit + E2E |
| GF0B-11 | Not found without leaks | a missing, another user's or a malformed course id shows the same not-found state; no name or count is revealed | unit + E2E (second user) |
| GF0B-12 | Rename course | PATCH `{name}`; same validation as creation; caches for that course and the course list updated | unit + E2E |
| GF0B-13 | Delete course | Destructive Modal; DELETE; on 204 the course and its documents are removed from the cache and the app goes to the Dashboard; 404 treated as already gone | unit + E2E |
| GF0B-14 | Client-side upload checks | `.pdf`, `.docx`, `.pptx` only, not empty, at most 100 MB; rejected files get a row with the reason and Remove; the same file selected twice is not queued twice; the server stays authoritative | unit |
| GF0B-15 | One request per file, progress | each file is its own `XMLHttpRequest` multipart upload (field `files`); progress per row (`role="progressbar"`); one file's rejection never affects another; the row's client id is replaced by the backend document id | unit + E2E |
| GF0B-16 | Upload queue | one transfer at a time; no new upload while 5 documents are processing; `queue_full` puts the row in Waiting and resumes when capacity frees (or offers Retry); `rate_limited` waits for `Retry-After`; network failures offer Retry; Cancel aborts a transfer; Remove drops a local row | unit |
| GF0B-17 | Server rejections on the row | `upload_rejected` per-file reason, `file_too_large`, `quota_exceeded`, `queue_full`, `rate_limited`, `not_found`, `duplicate: true` ("already in this course") | unit |
| GF0B-18 | Status mapping | in-progress statuses → Extracting; `ready` → Indexed; `failed` + `no_text`/`empty_file` → Empty; `failed` + `unsupported_type`/`type_mismatch`/`macro_document` → Not supported; other `failed` → Failed (Retry); no OCR status; every status is a text Tag, not colour only; frontend failure codes match the backend's `REASONS` | unit |
| GF0B-19 | Polling | `GET /courses/{id}/documents` about every 2 s while a visible document is in progress; paused while the tab is hidden; stops when all are terminal and on unmount; one poller per course list; bounded backoff on errors; stops after repeated failures with a "Try again" action | unit + E2E |
| GF0B-20 | Retry | shown for Failed only; one request at a time; on 202 the row returns to Extracting and polling resumes; `not_failed` and `queue_full` shown safely | unit + E2E |
| GF0B-21 | Delete document | Destructive Modal; button disabled while pending; removed from the cache only after 204; 404 treated as already deleted | unit + E2E |
| GF0B-22 | Download | authenticated `fetch` → Blob → object URL → download with the `Content-Disposition` file name; the object URL is revoked; never opened inline; 401 handled by refresh, 404 shown safely | unit + E2E |
| GF0B-23 | Query keys and cache | stable keys `["courses", {limit}]`, `["course", id]`, `["documents", courseId, {limit}]`, `["document", id]`; mutations invalidate only their own keys; logout still clears everything (GF0A-12); 4xx never retried; mutations never retried automatically | unit |
| GF0B-24 | Session expiry during an operation | a protected call or an upload answered 401 triggers one refresh and one retry; a second failure ends the session and returns to sign-in | unit |
| GF0B-25 | F-M4-03 — Frontend Rendering Safety | hostile course names and file names (`<script>alert(1)</script>`, `<img src=x onerror=alert(1)>`, `javascript:alert(1)`) render as inert text; no server value becomes an `href` scheme or HTML; static bans still active | unit + E2E |
| GF0B-26 | Error copy | every backend code used maps to frontend copy; no stack traces, paths, SQL or raw problem bodies shown; unknown codes fall back to a generic sentence | unit |
| GF0B-27 | Accessibility | axe: zero serious or critical violations on Dashboard, modal, Workspace and Upload; course creation and file upload complete with the keyboard only; upload outcomes announced politely, without progress noise; visible 2 px focus | E2E |
| GF0B-28 | Responsive (provisional) | no horizontal page overflow at 1440×900, 1024×768, 720×900 (200% zoom) and 390×844 (functional check only); controls stay usable | E2E |
| GF0B-29 | Token storage after the full flow | web storage holds nothing and `document.cookie` is empty after upload, download and deletion | E2E |
| GF0B-30 | CI | frontend workflow: the F0-A checks plus an embedding-model cache and the processing worker for E2E; OpenAPI drift check; real-backend Playwright | CI run + unit (workflow check) |

## 2. Decisions applied in F0-B

From the plan (11.1, 11.3) and the task brief; each is provisional where Figma has no answer.

| Topic | Decision |
|---|---|
| Undrawable data (plan 11.1, 11.3-1) | Dashboard shows the greeting header and "Your courses" only. Rows A and C (recommendation, streak, weakest topics, recent activity) are not rendered and leave no gap. Course cards show "n files" and a processing line; no mastery. The Workspace shows the "Files indexed" stat only; no Topics stat, mastery stat, Topics card, topic chips, tabs, OCR notice or "Ask your materials" (F1) |
| Greeting subtitle | the computed date only (UI §18 D-18); the exam countdown has no data |
| Sidebar items | Dashboard and Courses only. Analytics, Personalised exam, Settings and Data & privacy have no implemented destination yet and are hidden, not disabled |
| Sign-out (plan 11.3-5) | the user card (Sidebar) and the avatar (Rail) are buttons that open a small disclosure holding "Sign out". The user card shows the account's name and email (the Figma subtitle "Computer Science · Year 3" has no data) |
| Course creation (plan 11.3-2) | Modal "New course" with one field "Course name" and the buttons Cancel / Create course. Code and description are not collected (no Figma field) |
| Rename and delete course | Workspace title row: Secondary "Rename" and "Delete course". Rename uses the same Modal with "Save changes". Delete uses the Destructive Modal sample copy from UI §7.14, with the real file count |
| "Upload files" on the Dashboard (plan 11.3-3) | see GF0B-08 |
| Courses destination (plan 11.3-4) | `/courses` → `/#courses`; the Sidebar's Courses item links there; the breadcrumb's "Courses" is a link (UI §18 D-5) |
| Upload page list | the course's documents (server) plus this page's in-flight rows, newest first (D-13). Rows: Waiting (client-only, provisional), Uploading n%, Extracting, Indexed (Open → workspace with `?file=`), Failed (Retry), Not supported / Empty (Remove = delete with confirmation). An Extracting row has no Cancel: the backend cannot cancel processing (delete is offered in the workspace) |
| Leaving the upload page | in-flight transfers are aborted on unmount; already accepted files keep processing |
| Status copy | Figma strings where they exist (UI §7.16); Failed reasons use the backend's fixed sentences, mirrored in `features/documents/strings.ts` and checked against `REASONS` by a test |
| Size limit copy | "Up to 100 MB per file" is kept because the backend default is 100 MB (UI §10.7 open item now answered by code); the limit is a constant, checked against `config.py` by a test |
| Download | file kept in memory as a Blob before saving (at most 100 MB); acceptable for F0-B, streaming download noted for later |
| Toasts | bottom centre, 5 s, polite; used for "Course deleted.", "File deleted.", "Course renamed.", duplicates (UI §18 D-16) |
| Responsive fallback (provisional, not F3) | at 1024 px and wider: Sidebar or Rail as drawn. Below 1024 px: a top bar with the same two links and the user menu, and single-column content. Workspace: three columns from 1280 px, the details below the centre column from 1024 to 1279 px, one column below 1024 px. None of this claims Figma fidelity |
| Polling | 2 s; TanStack Query pauses intervals while the tab is hidden; backoff 2 s × 2^failures up to 30 s; stops after 6 failed attempts and shows "Status updates stopped" with Try again |

## 3. Known design gaps and blockers

| Item | Detail |
|---|---|
| Icons (visual blocker) | the 30 Figma SVGs are still not exported (UI A8). F0-B adds placeholder uses (Rail items, NavItems, Card, EmptyState bubble, dropzone, FileUploadRow tiles, IconButton close, Toast). The Rail's items are therefore blank 20 px boxes with accessible names and tooltips; the breadcrumb and the wordmark link back to the Dashboard. The close buttons of the Modal and Toast are also blank 44 px boxes (they have accessible names; Cancel and Escape remain the visible ways out). All uses are listed in `design-system/icons/placeholders.ts` |
| OCR status and notice | not exposed by the backend (plan 11.1); OCR files show as Extracting |
| Provisional copy | strings marked `PROVISIONAL` in `features/*/strings.ts` (empty dashboard, errors, Waiting row, delete-file dialog, not-found page) need approval |
| Unverified measurements | Workspace details meta rows and the upload list head spacing are taken from UI §8.3/8.4 text, not from a frame measurement |
| Mobile | final mobile layouts are F3; the fallback in section 2 is functional only |

## 4. Explicit exclusions

- **Features:** summaries, chat, quizzes, attempts, analytics, mastery, streak, weakest topics, recommendations,
  recent activity, personalised exams.
- **Account screens:** Settings, Data & privacy, export, account deletion.
- **Transport and processing:** push, WebSockets, SSE, OCR state, processing cancellation (no backend support).
- **Theme and layout:** dark-theme switch, final mobile navigation.
- **Backend:** no backend change. The E2E backend script only turns its own processing worker on.

## 5. F-M4-03 — Frontend Rendering Safety (F0-B coverage)

- **Text only:** course names, descriptions, file names, Tag text and error messages are rendered as React text
  children. No `dangerouslySetInnerHTML`, no Markdown, no HTML parsing.
- **Links:** built only from route templates and server ids (`/courses/${id}`), never from a server string's scheme.
  A file name never becomes an `href`. Download names are set on a programmatic anchor, never inserted as markup.
- **Tests:**
  - unit tests render the three hostile strings as course names and file names and assert there are no `script`,
    `img` or `javascript:` links in the DOM;
  - E2E creates such a course and uploads such a file, then asserts there is no dialog and no injected element;
  - static scans (GF0A-03, GF0A-07) and the ESLint bans stay active.

## 6. Changes to F0-A artefacts

- **GF0A-19:** the F0-A "integration placeholder" at `/` is replaced by the Dashboard (the brief requires it). The
  GF0A-19 tests now assert that the protected landing route shows the signed-in user and Sign out on the Dashboard.
- **Auth E2E:** sign-out is reached through the user menu (decision 2, sign-out placement).
- **E2E backend script:** the processing worker is enabled (`E2E_WORKER_ENABLED`, default on), so uploads reach
  real terminal states. Rate limits remain the real ones.

## 7. Evidence (local, 2026-11-25)

| Check | Result |
|---|---|
| `npm ci` (lockfile) | OK |
| `npm audit --audit-level=high` | 0 vulnerabilities |
| `npm run lint` | 0 problems (0 warnings) |
| `npm run typecheck` | 0 errors, also without the generated `next-env.d.ts` |
| `npm test` (Vitest) | 13 files, **126 passed**: 39 from F0-A and 87 new (`f0b-logic` 20, `f0b-components` 12, `f0b-transport` 9, `f0b-dashboard` 17, `f0b-workspace-upload` 27, traceability 2) |
| `npm run build` | OK: `/` 168 kB, `/courses/[courseId]` 170 kB, `/courses/[courseId]/upload` 133 kB first load |
| `npx playwright test` against a real backend with its worker | **16 passed** (5 F0-A + 11 F0-B), twice in a row; about 35 s locally including the production build. Real processing of the five fixtures takes about 15 s |
| OpenAPI drift (`npm run api:schema`, checksums and `git diff --exit-code`) | no drift |
| Backend regression (no backend file changed) | ruff clean; 402 backend tests OK (148 s) |
| CI | pending the push (the E2E job gains Tesseract, the model cache and a model pre-fetch; first run downloads about 130 MB) |

Every gate item is named by at least one test title; `tests/unit/traceability.test.ts` fails if one is not, and
checks the workflow for GF0B-30.

Found and fixed while testing:

| Problem | Effect | Fix |
|---|---|---|
| Course dialog reset its field in an effect after opening | the first keystrokes after opening could be erased (seen with fast keyboard input in E2E) | the form mounts when the dialog opens; no reset effect. The course chooser got the same fix |
| Renaming patched the cached course list, which marks it fresh | a course created since the list was fetched stayed hidden on the Dashboard | rename patches the list **and** invalidates it (unit regression test) |
| `queue_full` (HTTP 429) was handled like a rate limit | the upload queue paused for 60 s instead of offering Retry | only the `rate_limited` code pauses the queue (unit test) |
| Deleting a course removed its cache while the page still observed it | one wasted refetch of the deleted course | the page stops observing, then drops the cache |
| "Upload files" switched from disabled to enabled with a colour transition | axe sampled the transition as a contrast failure | the button shows its busy state instead; colours never change |
| The user card and avatar buttons used an `aria-label` that did not contain their visible text | WCAG 2.5.3 label-in-name (axe) | the visible text is the name, behind a screen-reader-only "Account:" prefix |
| "SELECTED FILE" eyebrow in `text/tertiary` on the canvas | just under 4.5:1 | `text/secondary`, the same decision as F0-A |

Notes:
- **React StrictMode:** in development it mounts components twice, so the first in-flight query is aborted (the query
  functions pass their `AbortSignal`) and fetched again. Tests use server state rather than reply order. Production
  builds fetch once.
- **E2E rate budget for one run, both suites:**
  - 3 registrations (the limit per hour per IP);
  - 5 logins, with the second F0-B login minutes after the others;
  - 6 uploads for one user (limit 20 per hour);
  - a few refreshes.

  The real limits are kept.
- **Escape** cancels every dialog, destructive ones included. Cancel is always safe; confirming always needs the
  explicit Danger button.

**Not verified here:** final Figma fidelity of the narrow-width fallback (provisional by design), screen-reader
announcements with a real screen reader (axe and DOM checks only), and the CI run.

## 8. Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| Frontend lead | Frontend Team (until assigned) | | |
| Backend lead | Mohamed Amir Kamal | | |
| Supervisor | Prof. Gamal Ebrahim | | |

F0 as a whole is complete only when this gate's local checks **and** the CI run are both green.

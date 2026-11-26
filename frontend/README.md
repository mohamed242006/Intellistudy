# IntelliStudy frontend

Next.js 15 (App Router), TypeScript (strict), Tailwind CSS v4, TanStack Query, React Hook Form, Zod.
Visual source of truth: [`../docs/figma_ui_context.md`](../docs/figma_ui_context.md). Plan and gates:
[`../docs/FRONTEND_IMPLEMENTATION_PLAN.md`](../docs/FRONTEND_IMPLEMENTATION_PLAN.md), [`../docs/F0A_GATE.md`](../docs/F0A_GATE.md),
[`../docs/F0B_GATE.md`](../docs/F0B_GATE.md), [`../docs/F1_GATE.md`](../docs/F1_GATE.md), [`../docs/F2_GATE.md`](../docs/F2_GATE.md).

**Status:** F0-A (foundations, Sign in, Sign up, session, route protection) and F0-B (Dashboard, courses, Course
Workspace, uploads with processing status, retry, download and deletion), F1 (grounded summaries and chat with
cited sources) and F2 (quiz generation, attempts, results and review).

| Route | Screen |
|---|---|
| `/signin`, `/signup` | authentication |
| `/` | Dashboard ("Your courses" at `/#courses`; `/courses` redirects there) |
| `/courses/[courseId]` | Course Workspace (`?file=` selects a file) |
| `/courses/[courseId]/upload` | Upload flow |
| `/courses/[courseId]/documents/[documentId]/summary` | Summary (`?source=n` opens a citation) |
| `/courses/[courseId]/chat` | Chat (`?c=` selects a conversation) |
| `/courses/[courseId]/quizzes` | Course quizzes and the generation form (`?document=` preselects a file) |
| `/quizzes/[quizId]` | Quiz status, Start or Continue, attempt history |
| `/quizzes/[quizId]/attempts/[attemptId]` | Taking a quiz |
| `/attempts/[attemptId]/review` | Results and review |

## Run

Requirements: Node.js 22.12 or later (CI uses 24.22.3), and the backend running on `http://127.0.0.1:8000` (see
[`../backend/README.md`](../backend/README.md)).

```bash
cd frontend
npm ci
npm run dev            # http://localhost:3000  (use "localhost", which is in the backend's CORS/CSRF allowlist)
```

`/api/v1/*` is rewritten to the backend (same origin), so the refresh cookie and CSRF header work.
Set `INTELLISTUDY_API_ORIGIN` (server-side only, see `.env.example`) to point at another backend.
**It is read when the app is built:** `next build` writes the rewrite target into `.next/`, so a production build made
without it talks to `http://127.0.0.1:8000` whatever `next start` is given. Set it for `next build`, not only for
`next start`.

## Checks

```bash
npm run lint && npm run typecheck && npm test && npm run build
npx playwright install chromium && npm run e2e     # isolated backend 8100, test provider 8101, frontend 3100
```

The end-to-end suite starts a throwaway backend with `scripts/e2e-backend.sh`:
- a fresh SQLite database and file storage in a temporary directory, never `data/backend/`;
- it never reads `.env`;
- no LLM provider;
- the processing worker on (since F0-B), so uploads reach real terminal states with the real embedding model (loaded
  offline from the local cache; `E2E_HF_OFFLINE=0` allows a first download);
- a **deterministic test provider** (`tests/e2e/fixtures/stub_llm.py`, F1; quizzes since F2) through the backend's
  `local` provider slot:
  no key, no real model, no network. Retrieval, grounding, citation validation and answer states are the backend's
  real code;
- the real rate limits;
- explicit ports only: `scripts/e2e-backend.sh` and `scripts/e2e-frontend.sh` refuse a missing target and port 8000,
  and the frontend script checks the built rewrite before starting. The temporary directory and processes are removed
  on exit.

Upload fixtures (PDF, PPTX, DOCX, an empty PDF and a damaged PDF) are generated into a temporary directory by
`tests/e2e/fixtures/make_fixtures.py`; `data/uploads/` is never used.

It uses the repository's `.venv` Python when present; set `E2E_PYTHON` to choose another interpreter.

## Uploads, brand assets and motion

- **Upload size.** One file per request, up to the backend's `max_upload_bytes` (100 MB). The `/api/v1` rewrite is a
  Next.js proxy, and Next.js 15 cuts proxied request bodies at `experimental.middlewareClientMaxBodySize` (default
  10 MB), so `next.config.ts` raises it to the per-file limit plus 1 MiB of multipart framing. Both numbers live in
  `features/upload/limits.ts`. Before sending, the browser checks the extension, the size and the file signature
  (`%PDF-` or a ZIP container for DOCX/PPTX); the backend repeats every check and stays authoritative.
- **Brand assets.** `public/brand/intellistudy-logo.svg` and `public/images/intellistudy-background.webp` are
  **placeholders** (no final logo or background exists yet). Replace the files at the same paths. The paths are set in
  `design-system/brand.ts`; see `public/brand/README.md`.
- **Design source.** `docs/DESIGN_SPEC_NEW.md` (v2.0) is the design source. Tokens are generated from
  `design-system/tokens/tokens.ts` (`npm run tokens`) and tested against the spec's tables.
- **Motion.** Utilities in `app/globals.css` (`motion-enter`, `motion-enter-fast`, `motion-stagger`, `motion-pulse`,
  `motion-dots`, `motion-progress`) use the spec's motion tokens (120/200/300 ms). They animate only opacity and
  transform, so they cause no layout shift. Under `prefers-reduced-motion: reduce`, entrances and pulses are off and
  only the status spinner keeps turning. Playwright runs with reduced motion so the accessibility checks see final
  frames.

## Adding materials, summaries and quizzes from several files

- **Add materials.** Choosing or dropping files only stages them; every check (type, size, signature) runs right
  away. "Add this file" / "Add these files" submits the staged files, which upload one at a time. When the backend has
  accepted every file, the page shows a short success state, fades out (220 ms after 300 ms; no animation under reduced
  motion) and opens the course workspace with `router.push`, where processing continues visibly. If some files fail,
  the page shows how many were added and how many failed, keeps the failed rows (Retry, Remove) and offers "Continue
  with uploaded files". Leaving with staged or uploading files asks first: a dialog for links inside the app, the
  browser prompt for reloads. The browser's Back button is not intercepted.
- **File selection.** `features/documents/components/DocumentPicker.tsx` (logic in `features/documents/selection.ts`)
  is the one selector for Summary and Quiz. Only ready files can be selected, at most 20.
- **Summaries.** `/courses/{id}/summaries` creates a summary: one file uses that file's own summary
  (`POST /documents/{id}/summary`, unchanged); two or more create one combined summary
  (`POST /courses/{id}/summaries` with `{"document_ids": [...]}`), shown at `/summaries/{id}` with sections grouped
  by file.
- **Quizzes.** `POST /courses/{id}/quizzes` always sends the explicit `document_ids`. `?document=<id>` still
  preselects a file on both pages.

## Generated files

| File | Source | Regenerate |
|---|---|---|
| `design-system/tokens/tokens.css` | `design-system/tokens/tokens.ts` (Figma values, UI §4) | `npm run tokens` |
| `lib/api/openapi.json`, `lib/api/schema.d.ts` | the backend's OpenAPI schema, exported in-process | `npm run api:schema` (backend Python environment active) |

Tests fail when either drifts from its source.

## Rules

- **Tokens:** access tokens live in memory only; never in web storage or URLs.
- **Model output:** server and model text is rendered as text, never as HTML (`dangerouslySetInnerHTML` is banned
  by lint and a test; F-M4-03 — Frontend Rendering Safety).
- **Colours:** components use semantic tokens only; there are no hex literals outside the generated token
  stylesheet.
- **Icons:** the 30 Figma icons are placeholders until they are exported
  (`design-system/icons/placeholders.ts`).
- **Server state:** TanStack Query only, with the keys in `lib/query/keys.ts`; no other global store. Uploads use one
  `XMLHttpRequest` per file (`lib/api/upload.ts`) for progress; everything else goes through `lib/api/client.ts`.

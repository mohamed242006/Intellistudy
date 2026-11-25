# IntelliStudy frontend

Next.js 15 (App Router), TypeScript (strict), Tailwind CSS v4, TanStack Query, React Hook Form, Zod.
Visual source of truth: [`../docs/figma_ui_context.md`](../docs/figma_ui_context.md). Plan and gates:
[`../docs/FRONTEND_IMPLEMENTATION_PLAN.md`](../docs/FRONTEND_IMPLEMENTATION_PLAN.md), [`../docs/F0A_GATE.md`](../docs/F0A_GATE.md).

**Status:** F0-A, foundations and secure authentication (Sign in, Sign up, session, route protection). The landing
route `/` is an F0-A integration placeholder, not the Dashboard.

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

## Checks

```bash
npm run lint && npm run typecheck && npm test && npm run build
npx playwright install chromium && npm run e2e     # starts its own backend (port 8100) and frontend (port 3100)
```

The end-to-end suite starts a throwaway backend with `scripts/e2e-backend.sh`:
- a fresh SQLite database in a temporary directory, never `data/backend/`;
- it never reads `.env`;
- no LLM provider;
- the real rate limits.

It uses the repository's `.venv` Python when present; set `E2E_PYTHON` to choose another interpreter.

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

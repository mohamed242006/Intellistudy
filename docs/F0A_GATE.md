# F0-A Gate: Frontend Foundations and Secure Authentication

**Scope:** milestone F0-A of [`FRONTEND_IMPLEMENTATION_PLAN.md`](FRONTEND_IMPLEMENTATION_PLAN.md): the Next.js
foundation, design tokens, AuthShell, Sign in, Sign up, the typed API client, in-memory authentication with refresh,
route protection, tests and CI. **Out of scope:** Dashboard, courses, upload and every later screen (F0-B onwards).
**Version:** 1.0, 2026-11-25, written before implementation.
**Sources, in priority order:**
1. The backend implementation: `backend/app/api/v1/auth.py`, `schemas.py`, `api/deps.py`, `services/auth.py`,
   `core/passwords.py`, `core/errors.py`.
2. The security contract.
3. Figma ([`figma_ui_context.md`](figma_ui_context.md), cited as "UI §n").
4. The plan.

## 0. Verified backend contract (F0-A)

| Endpoint | Request | Success | Failures used by the UI |
|---|---|---|---|
| `POST /api/v1/auth/register` | `{email (3-320), name (1-200; 1-100 after normalisation), password}`, unknown fields rejected | 201 `UserOut{id,email,name,role,created_at}`, **no session** | 422 `invalid_email` / `invalid_name` / `weak_password` (client-safe `detail`), 409 `registration_rejected` (generic), 422 `validation_error`, 429 `rate_limited` + `Retry-After` |
| `POST /api/v1/auth/login` | `{email, password}` | 200 `{access_token, token_type: "bearer", expires_in}` + cookie `__Secure-is_refresh` (`HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`) | 401 `invalid_credentials` "Invalid email or password." for unknown email, wrong password, locked or disabled account; 429 |
| `POST /api/v1/auth/refresh` | no body; cookie; header `X-Requested-With: IntelliStudy`; `Origin`, if sent, in the CORS allowlist | 200 token + rotated cookie | 401 (cookie cleared), 403 `csrf_rejected` |
| `POST /api/v1/auth/logout` | cookie + `X-Requested-With: IntelliStudy` | 204, cookie cleared | 403 `csrf_rejected` |
| `GET /api/v1/auth/me` | `Authorization: Bearer` (exactly one header) | 200 `UserOut` | 401 generic, `WWW-Authenticate: Bearer` |

Errors are RFC 7807 bodies: `type` = `about:blank#<code>`, `title`, `status`, `request_id`, optional `detail`, and for
validation errors `errors[{loc, type}]`. Submitted values are never echoed back.

Password policy (`core/passwords.py`):
- 10 to 128 characters;
- at least one letter and one digit;
- not a common password (checked by the server only).

The backend enforces **no** `.edu` rule.

## 1. Gate items

Every item has a test. "Unit" = Vitest + Testing Library; "E2E" = Playwright against a real backend started for the
run.

| ID | Item | Expected result | Test |
|---|---|---|---|
| GF0A-01 | Design tokens | Semantic Light and Dark values equal UI §4.1.2; spacing, radii, shadows, type styles equal UI §4.2-4.5; components reference semantic tokens only | unit (token file parsed against the table) |
| GF0A-02 | No raw colours in components | no hex colour literal outside the token stylesheet | unit (static scan) |
| GF0A-03 | Rendering safety (F-M4-03 — Frontend Rendering Safety) | `dangerouslySetInnerHTML` appears nowhere in frontend source; ESLint rule and static test | unit (static scan) + lint |
| GF0A-04 | Button | Primary, Secondary and Ghost variants; 44 px high; Loading sets `aria-busy` and blocks clicks; Disabled is not interactive | unit |
| GF0A-05 | Input | label bound to the field; helper through `aria-describedby`; Error sets `aria-invalid`, shows the message as text; Disabled | unit |
| GF0A-06 | Auth validation mirrors the backend | sign-up: email pattern and 320 max, name 1-100 after whitespace normalisation, password 10-128 with a letter and a digit; sign-in: both fields required; no `.edu` rule | unit |
| GF0A-07 | Token storage | the access token is held in memory only; no `localStorage` / `sessionStorage` use anywhere in source; never placed in a URL | unit (store + static scan) + E2E (web storage empty) |
| GF0A-08 | Authorization header | added only when a token exists; never sent to `/auth/refresh` or `/auth/logout` | unit |
| GF0A-09 | One refresh, one retry | a protected request answered 401 triggers one refresh and one retry; a second 401 clears the session and reports expiry | unit |
| GF0A-10 | Concurrent 401s | several requests failing together share one refresh operation | unit |
| GF0A-11 | Cross-tab coordination | refresh runs under `navigator.locks` when available (in-tab single flight otherwise); logout is broadcast on a `BroadcastChannel` and clears other tabs | unit |
| GF0A-12 | Logout | calls `/auth/logout` with the CSRF header, clears the token and the TanStack Query cache, broadcasts | unit |
| GF0A-13 | Error mapping | problem `type` codes map to typed errors: `validation_error`, `invalid_credentials` (generic text, no account hint), `registration_rejected` (generic), `weak_password` / `invalid_email` / `invalid_name` to their fields, `rate_limited` with `Retry-After`, network failure, session expiry, safe fallback; no stack traces or internals shown | unit |
| GF0A-14 | Sign in | success stores the token, loads `/auth/me`, goes to the protected landing route (or a safe same-origin `next`) | unit (integration) + E2E |
| GF0A-15 | Sign in with bad credentials | one generic message, identical for unknown email and wrong password | unit (integration) |
| GF0A-16 | Sign up | client validation; success registers, then signs in with the credentials held only in memory, then lands; password is not kept | unit (integration) + E2E |
| GF0A-17 | Startup | exactly one refresh at startup; success restores the session, failure shows the sign-in route for protected pages | unit (integration) + E2E (reload keeps the session) |
| GF0A-18 | Route protection | an anonymous visit to a protected route goes to `/signin?next=…` (same-origin paths only); signed-in users visiting auth pages go to the landing route | unit (integration) + E2E |
| GF0A-19 | Protected placeholder | the landing route is clearly labelled as an F0-A integration placeholder, shows the signed-in user from `/auth/me`, offers Sign out; it is not the Dashboard | unit + E2E |
| GF0A-20 | Rate limiting | a 429 shows a safe message with the wait time from `Retry-After` | unit (integration) |
| GF0A-21 | Auth screens fidelity | at 1440×900: brand panel 640 wide; card 440 wide, padding 40, gap 24, radius 16; controls 44 high; copy from UI §8.1.4 except the two backend-conflicting strings (section 2) | E2E (computed geometry) |
| GF0A-22 | Accessibility | axe: zero serious or critical violations on `/signin`, `/signup` and the placeholder; keyboard order tabs → fields → submit; visible 2 px focus; errors announced; no horizontal overflow at 1440 and at 720 (200% zoom of 1440) | E2E |
| GF0A-23 | CI | frontend job: lockfile install, lint, type-check, unit tests, production build, static security checks; E2E job with a real backend; OpenAPI drift check | CI run |

## 2. Decisions applied in F0-A (from the approved plan and the task brief)

- **Password copy follows the backend:**

  | Field | Figma copy | F0-A copy |
  |---|---|---|
  | Password placeholder | "At least 12 characters" | "At least 10 characters" |
  | Password helper | "Use 12 or more characters. A phrase works well." | "Use 10 or more characters, with at least one letter and one number." |

  The `.edu` error sample is not used.
- **"Forgot your password?"** is rendered for fidelity as a disabled control, with a screen-reader note that password
  reset is not available yet. No route exists for it.
- **"Terms" and "Privacy Policy"** in the legal line are plain text: no destination exists.
- **Form-level errors** (wrong credentials, rejected registration, rate limit, network) use the Notice component.
  Its Warning tone comes from the library (UI §7.15b), inside a `role="alert"` region. Figma has no form-level error
  design; this copy is provisional and listed in `features/auth/strings.ts`.
- **Narrow viewports:** UI C16 (how the brand panel behaves below desktop width) is undecided. So that 200% zoom
  stays usable, the panel and the form **stack** when the window is narrower than 1080 px (640 + 440). This adds no
  visual element and is provisional until C16 is decided.
- **Icons:** the 30 Figma SVGs are not in the repository (UI A8). The Wordmark, trust points, input error icons and
  the button spinner use typed placeholders that keep the exact box size and render no glyph. Each placeholder is
  listed in `design-system/icons/placeholders.ts` as a visual blocker.
- **Unverified measurements:** the brand panel's vertical alignment and the spacing between trust-point rows are not
  recorded in UI §8.1.4. F0-A uses the panel gap of 32 between blocks, 16 between trust rows and 12 between icon and
  text. These must be checked against the Figma frame.

## 3. Evidence (local, 2026-11-25)

| Check | Result |
|---|---|
| `npm ci` (lockfile) | OK |
| `npm audit --audit-level=high` | 0 vulnerabilities (Next.js 15's bundled PostCSS 8.4.31 overridden to 8.5.33; see section 4) |
| `npm run lint` (ESLint 9, includes the F-M4-03 and web-storage bans) | 0 problems |
| `npm run typecheck` (strict, `noUncheckedIndexedAccess`) | 0 errors, also without the generated `next-env.d.ts` |
| `npm test` (Vitest, 8 files) | 39 passed: GF0A-01..13 unit, GF0A-14..20 integration, traceability and GF0A-23 workflow check |
| `npm run build` (Next.js production) | OK: `/signin` and `/signup` 146 kB first load |
| `npx playwright test` against a real backend | 5 passed: GF0A-21 geometry, GF0A-22 axe / keyboard / focus / overflow at 1440 and 720, sign-up, sign-in with reload restore and sign-out protection, generic bad-credentials message |
| OpenAPI drift (`npm run api:schema`, checksums) | no drift |
| Backend regression (no backend file changed) | ruff clean; 402 backend tests OK |

Found and fixed while testing:
- **Placeholder contrast:** axe flagged `text/tertiary` on `bg/canvas` on the placeholder page (just under 4.5:1;
  Figma uses that pair only on white surfaces), so the placeholder now uses `text/secondary`.
- **Empty alert spacing:** the empty form-level alert region added a 24 px gap under the heading. It is now visually
  hidden while empty (still announced), and an end-to-end assertion checks the 24 px spacing.

## 4. Known limitations (recorded, not blocking F0-A)

| Item | Detail |
|---|---|
| Icons (visual blocker) | 30 Figma SVGs not exported (UI A8); F0-A uses typed, empty, size-exact placeholders (`design-system/icons/placeholders.ts`) |
| ESLint 9 | marked unsupported upstream, but `eslint-config-next` 15.5.29 supports ESLint 9 at most; revisit with Next.js 16 |
| PostCSS override | `overrides.next.postcss = 8.5.33` fixes GHSA-qx2v-qp2m-jg93 and related advisories without moving to Next.js 16 (the team chose 15) |
| No Web Locks | without `navigator.locks` (very old browsers), refreshes are single-flight per tab only; two such tabs refreshing in the same instant could trigger reuse detection (RT-05) and sign the user out |
| Content-Security-Policy | page CSP (nonce-based) is planned for F4; F0-A sends `nosniff`, `no-referrer`, `X-Frame-Options: DENY` and a restrictive `Permissions-Policy` |
| Provisional copy | form-level messages in `features/auth/strings.ts` (`PROVISIONAL`) need approval |
| Unverified measurements | brand-panel vertical alignment and trust-row spacing (section 2) to be checked against the Figma frame |

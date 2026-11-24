# IntelliStudy backend

FastAPI service for the backend vertical slice. **Security reference:**
[`docs/backend_security_contract.md`](../docs/backend_security_contract.md). Rule ids from that document (OWN-03,
RET-06, ...) are cited in code and tests.

## Status

| Milestone | Scope | State |
|---|---|---|
| M0 | Foundations + security baseline: settings, logging with redaction, RFC 7807 errors, security headers, CORS allowlist, body limits, rate-limit scaffold, SQLAlchemy + Alembic, LLM provider interface (DeepSeek / OpenAI / local), AI service container, `/api/v1/health`, CI | done |
| M1 | Identity, courses, ownership: register/login/refresh/logout/logout-all/me/change-password, Argon2id, HS256 access tokens, rotating refresh tokens with reuse detection, lockout, rate limits, course CRUD through `get_owned`; release gate `docs/SECURITY_MERGE_GATE.md` (79 items, all passing) | done (CI green) |
| M2 | Documents and processing: streaming upload, file validation, ZIP-bomb and encryption checks, ownership-safe storage, sandboxed parser process, job runner; gate M2 section (39 items) | done (CI green) |
| M3 | Grounded chat: conversations, messages, READY-only scoped retrieval, citation validation, answer sanitising, chat states, provider failure handling, token budget; release gate `docs/M3_RELEASE_GATE.md` (52 items, all passing; F-M2-10 closed) | done (CI green) |
| M4 | Summaries + quiz generation | next (release gate to be written first) |
| M5 | Quiz taking, end-to-end demo, security verification | planned |

## Run locally (demo profile)

From the repository root, with the project `.venv` (Python 3.12, see `requirements.lock.txt`):

```bash
cp .env.example .env                       # .env is git-ignored; never commit it
python -c "import secrets; print(secrets.token_urlsafe(32))"   # paste as INTELLISTUDY_JWT_SECRET in .env
# put the DeepSeek key in INTELLISTUDY_DEEPSEEK_API_KEY (optional in demo: without it, LLM features answer
# "llm_unavailable")

python -m backend.app.db.migrate           # create / upgrade the SQLite database
uvicorn --factory backend.app.main:create_app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/api/v1/health` or the interactive docs at `/docs` (disabled in `prod`).

## Endpoints (M1-M2)

| Method and path | Auth | Notes |
|---|---|---|
| `POST /api/v1/auth/register` | - | 201 with the profile; 3 per hour per IP |
| `POST /api/v1/auth/login` | - | access token in the body; refresh token only in the `__Secure-is_refresh` cookie (`HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`); 5 per minute per IP and per account; 15-minute lock after 5 failures |
| `POST /api/v1/auth/refresh` | refresh cookie + `X-Requested-With: IntelliStudy` | rotates the refresh token; reuse of an old one revokes the whole session family |
| `POST /api/v1/auth/logout` | refresh cookie + `X-Requested-With: IntelliStudy` | revokes this session family |
| `POST /api/v1/auth/logout-all` | Bearer | revokes every session and every existing access token |
| `POST /api/v1/auth/change-password` | Bearer | revokes everything, returns a fresh session |
| `GET /api/v1/auth/me` | Bearer | own profile |
| `POST/GET /api/v1/courses`, `GET/PATCH/DELETE /api/v1/courses/{id}` | Bearer | owner-scoped; another user's or a malformed id is the same 404; deleting a course removes its documents, vectors and files |
| `POST /api/v1/courses/{id}/documents` | Bearer | multipart field `files` (1-10 PDF/DOCX/PPTX, 100 MB each); 202 with `queued` documents; rejected files listed with reason codes |
| `GET /api/v1/courses/{id}/documents`, `GET /api/v1/documents/{id}` | Bearer | status (`queued`, `extracting`, `embedding`, `indexing`, `ready`, `failed`), progress, page/chunk counts, `error_code` + `error_message` |
| `GET /api/v1/documents/{id}/file` | Bearer | the original, as an attachment |
| `POST /api/v1/documents/{id}/retry`, `DELETE /api/v1/documents/{id}` | Bearer | retry failed documents; delete removes vectors, parents and the file |
| `POST/GET /api/v1/courses/{id}/conversations` | Bearer | create (optional `title`) / list the course's conversations |
| `GET/DELETE /api/v1/conversations/{id}` | Bearer | detail with the message history / delete |
| `POST /api/v1/conversations/{id}/messages` | Bearer | `question` (1-2000 characters), optional `document_ids`; answers only from the course's `ready` documents; `state` is `answered`, `partial`, `low_confidence` or `refused` (with `refusal_reason` and `notice`); numbered citations with document, page/slide and passage. Render `text` as plain text, never as HTML |

Access tokens are accepted only in `Authorization: Bearer ...` (never query strings or cookies). The browser keeps
the access token in memory and calls `refresh` when it expires (15 minutes). Over plain `http://localhost` browsers
still store `Secure` cookies; other HTTP clients may not.

## Configuration

All settings are environment variables with the prefix `INTELLISTUDY_` (see `.env.example` and
`backend/app/core/config.py`). Secrets are read only from the environment, held as `SecretStr` and masked in logs.

| Variable | Default | Notes |
|---|---|---|
| `INTELLISTUDY_PROFILE` | `demo` | `prod` refuses to start without strong secrets and disables `/docs` |
| `INTELLISTUDY_JWT_SECRET` | (required) | at least 32 random bytes; placeholders are rejected |
| `INTELLISTUDY_LLM_PROVIDER` | `deepseek` | `deepseek`, `openai`, `local`, `none` |
| `INTELLISTUDY_LLM_MODEL` | provider default | `deepseek-chat` for DeepSeek (validated configuration) |
| `INTELLISTUDY_DEEPSEEK_API_KEY` / `INTELLISTUDY_OPENAI_API_KEY` | - | required in `prod` for the selected hosted provider |
| `INTELLISTUDY_DATABASE_URL` | `sqlite:///data/backend/intellistudy.sqlite3` | a PostgreSQL URL works without code changes |
| `INTELLISTUDY_CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173,http://127.0.0.1:5173` | comma-separated; wildcards rejected |
| `INTELLISTUDY_MAX_UPLOAD_BYTES` | 100 MB | per file (used from M2) |
| `INTELLISTUDY_LLM_DAILY_TOKEN_BUDGET` | 200000 | prompt + completion tokens per user per UTC day; 429 before any provider call when spent |
| `INTELLISTUDY_CHAT_RETRIEVAL_K` / `INTELLISTUDY_CHAT_MAX_TOKENS` | 6 / 700 | sources per answer / answer length cap |

## Tests and checks

```bash
python -m unittest discover -s backend/tests -t .   # backend
python -m unittest discover -s tests -t .           # ai/ (INTELLISTUDY_SKIP_SLOW=1 to skip slow tests)
python -m ruff check ai backend tests evaluation
python -m mypy ai backend
```

CI (`.github/workflows/backend.yml`) also runs gitleaks on the full history and `pip-audit` on the lock file. Ignored
audit findings are recorded with reasons in the contract, Appendix C. Local hooks: `pre-commit install`.

## Layout

```
backend/
  app/
    main.py              create_app() factory (no module-level app: importing reads no environment)
    core/                config, clock, passwords (Argon2id + policy), tokens (JWT), logging (redaction, security
                         events), errors (RFC 7807), middleware, ratelimit
    db/                  base (portable types), session (SQLite pragmas), models, migrate
    providers/           LLMProvider interface; DeepSeek / OpenAI / Local (FutureLocalProvider) providers; factory
    services/            auth, ownership (get_owned), courses, documents, uploads (streaming receiver), storage,
                         sandbox (runs and validates the parser child), jobs (runner), ai_container (the only module
                         touching stores)
    worker/              code that runs inside the sandboxed parser process: preflight checks, parse_child entry point
    api/v1/              routers: health, auth, courses; schemas (every request model forbids unknown fields)
  migrations/            Alembic environment and revisions
  tests/                 unittest suites: M0 tests, static architecture rules, and the M1 gate tests test_g1_*.py
                         (one test per gate item; test_g1_m0.py checks the mapping stays one-to-one)
```

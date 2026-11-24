# IntelliStudy backend

FastAPI service for the backend vertical slice. **Security reference:**
[`docs/backend_security_contract.md`](../docs/backend_security_contract.md). Rule ids from that document (OWN-03,
RET-06, ...) are cited in code and tests.

## Status

| Milestone | Scope | State |
|---|---|---|
| M0 | Foundations + security baseline: settings, logging with redaction, RFC 7807 errors, security headers, CORS allowlist, body limits, rate-limit scaffold, SQLAlchemy + Alembic, LLM provider interface (DeepSeek / OpenAI / local), AI service container, `/api/v1/health`, CI | done |
| M1 | Identity, courses, ownership | next |
| M2-M5 | Documents and processing, grounded chat, summaries + quiz generation, quiz taking + demo | planned |

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
    core/                config, logging (redaction, security events), errors (RFC 7807), middleware, ratelimit
    db/                  base (portable types), session (SQLite pragmas), models, migrate
    providers/           LLMProvider interface; DeepSeek / OpenAI / Local (FutureLocalProvider) providers; factory
    services/            ai_container (lazy embedder, reranker, stores, retrieval; the only module touching stores)
    api/v1/              routers (M0: health)
  migrations/            Alembic environment and revisions
  tests/                 unittest suites, incl. static architecture rules (test_static_rules.py)
```

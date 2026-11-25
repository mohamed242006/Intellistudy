# Contributing to IntelliStudy

This guide explains how the project is built and how a change gets accepted. Reviewers can read it as a description
of the engineering process. Team members can follow it as a checklist.

## 1. Set up

Requirements: Linux or macOS, Python 3.12, Tesseract OCR (`sudo apt-get install tesseract-ocr`), git.

```bash
git clone https://github.com/mohamed242006/Intellistudy.git && cd Intellistudy
python3.12 -m venv .venv && source .venv/bin/activate
pip install uv && uv pip install -r requirements.lock.txt     # the pinned, audited lock file
cp .env.example .env                                           # .env is git-ignored: never commit it
python -c "import secrets; print(secrets.token_urlsafe(32))"   # paste as INTELLISTUDY_JWT_SECRET in .env
python -m backend.app.db.migrate                               # create / upgrade the database
uvicorn --factory backend.app.main:create_app --host 127.0.0.1 --port 8000
```

The interactive API documentation is at `http://127.0.0.1:8000/docs` (demo profile only). Without a DeepSeek key the
AI features answer `llm_unavailable`; everything else works.

## 2. Repository layout

| Path | Contents |
|---|---|
| `ai/` | AI pipeline: ingestion, chunking, embeddings, vector store, retrieval, answering |
| `backend/app/` | FastAPI application: `api/v1` routes, `services`, `db` models, `core` (config, security), `worker` (sandboxed parser) |
| `backend/migrations/` | Alembic migrations (one per milestone that changed the schema) |
| `backend/tests/` | backend tests, including one test per release-gate item (`test_g<milestone>_*.py`) |
| `tests/` | `ai/` pipeline tests |
| `evaluation/` | offline retrieval and answer evaluation harnesses (never imported by product code) |
| `docs/` | security contract, release gates, architecture, plans and records |

## 3. How a change is accepted

1. **Branch** from the integration branch and keep one topic per branch.
2. **Follow the security contract.** [`docs/backend_security_contract.md`](docs/backend_security_contract.md) is
   authoritative for all backend work. Cite rule ids (for example `OWN-03`) in code comments and tests. A MUST rule is
   never waived without a recorded contract change.
3. **New milestone = new gate first.** Before implementation, a release gate document lists every item as a test
   case with its expected result. The team approves it; only then is code written.
4. **One test per gate row.** Gate tests are named `test_g<n>_<area>_<nn>_...`. A traceability test fails on any
   missing or extra gate test. A row passes only without skips.
5. **Run the checks locally** (CI runs the same):

   ```bash
   python -m ruff check ai backend tests evaluation
   python -m mypy ai backend
   python -m unittest discover -s backend/tests -t .   # backend, about 2.5 minutes
   python -m unittest discover -s tests -t .           # ai pipeline, about 35 seconds
   ```

6. **Push and wait for CI** (`.github/workflows/backend.yml`): secret scan (gitleaks), dependency audit (pip-audit),
   lint, types and both test suites. A milestone is signed off only on a green run, recorded in its gate.
7. **Record findings.** Anything learned during implementation (a bug, a residual risk, a masked test) goes into the
   contract's Appendix D as `F-M<n>-<nn>`, with its resolution.

## 4. Rules that are enforced by tests

| Rule | How it is enforced |
|---|---|
| Every read of user data goes through `services/ownership.get_owned` (same 404 for missing, foreign and malformed ids) | isolation tests in every gate; `test_g5_security.py` calls every id route as another user |
| Every new route must be declared in the route map of `backend/tests/test_g5_security.py` | a route not in the map fails the build until its expected behaviour is declared |
| Request models extend `RequestModel` (unknown fields rejected) | G5-SEC-06 enumerates every request body |
| Only `AIContainer` touches the vector and parent stores; retrieval only through the READY-only layer | static rule tests (`test_static_rules.py`, G1-M0-07) |
| Answer keys are never serialised by an API module | G4-KEY-03, G5-KEY-05 static checks |
| Model output is data: never executed, rendered as text by any client (UPL-15) | prompt-injection tests; frontend rule in the release plan |
| No secrets in the repository, logs or responses | gitleaks (pre-commit and CI), redaction tests |

## 5. Adding an endpoint (checklist)

- [ ] The gate or contract item it implements is identified.
- [ ] Ownership: `get_owned` (or the scoped retrieval layer) before any work; `owner_id` in every query.
- [ ] Rate limit added to `core/ratelimit.LIMITS` if it writes or calls a model.
- [ ] Request model extends `RequestModel`; response model exposes no internal or secret fields.
- [ ] Route added to `ROUTES` in `backend/tests/test_g5_security.py` (with a valid example body).
- [ ] Tests for: another user (same 404), random and malformed ids, invalid input (422), the happy path.
- [ ] `backend/README.md` endpoint table updated.

## 6. Commits and secrets

- Commit messages: an imperative subject line, then a body explaining **why**, the evidence (tests, CI run) and any
  gate or contract change.
- Never commit `.env`, keys, tokens or real student data. API keys exist only in backend environment variables.
- Dependencies change only through `requirements.lock.txt`, and `pip-audit` must stay clean (exceptions are recorded in
  the contract's Appendix C).

## 7. Reporting a security issue

Do not open a public issue. Contact the backend lead (Mohamed Amir Kamal) directly. If a secret leaked, follow contract
rule SEC-10: revoke it at the provider (or rotate the JWT secret), deploy the new value, purge it from history, and
record the incident in `docs/`.

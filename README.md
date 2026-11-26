# IntelliStudy

**An AI study assistant that works only from your own lecture files, and always shows where an answer comes from.**

Graduation project, Ain Shams University (2026). Backend milestones M0-M5 are complete and approved; CI runs on every
push.

IntelliStudy helps students study from their own lecture files. Upload PDFs, slides or Word documents, then:

- **Ask questions.** Answers come only from your material, with numbered citations to pages and slides. Questions
  your lectures don't cover are refused, not guessed.
- **Summarise.** A structured summary of each document, every sentence cited.
- **Quiz yourself.** Multiple-choice and true/false quizzes whose answers are proven by quotes from your lectures. Grading
  is instant, with a cited explanation for every mistake and a retry of the questions you missed.

## Engineering highlights

- **Retrieval-Augmented Generation:** BGE embeddings (`BAAI/bge-small-en-v1.5`), ChromaDB search scoped to each user
  and course, cross-encoder re-ranking, and a relevance threshold calibrated on 87 labelled queries.
- **Grounded answers:** every sentence is checked against its cited passage; unsupported sentences are removed. On 111
  gold cases with DeepSeek: refusal recall 37/37, correct source cited 95%.
- **Secure document processing:** file type checked by content, ZIP-bomb and macro detection, parsing in a sandboxed
  process with no access to secrets and with CPU, memory and time limits.
- **Trustworthy quizzes:** answers validated deterministically against quoted evidence (no AI judge); answer keys never
  leave the server before submission; submitted attempts can never be changed.
- **Security by contract:** a written security contract, enforced by **298 release-gate tests** across five
  milestones and an OWASP Top 10 / OWASP Top 10 for LLM Applications review with no open item.
- **Tested on every push:** 402 backend tests, 800 AI-pipeline tests, ruff, mypy, gitleaks and pip-audit.

Measured with real lectures and DeepSeek:

| Measure | Result |
|---|---|
| 44-page PDF processed | 10.4 s |
| 10-question quiz generated | 18.1 s (10 of 10) |
| Answer save / grading | 2-7 ms / 10 ms |

## Quick start

Requirements: Python 3.12, Tesseract OCR, Linux or macOS.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install uv && uv pip install -r requirements.lock.txt
cp .env.example .env        # never commit .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # put into INTELLISTUDY_JWT_SECRET
# optional: INTELLISTUDY_DEEPSEEK_API_KEY=... (without it, AI features answer "llm_unavailable")
python -m backend.app.db.migrate
uvicorn --factory backend.app.main:create_app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the interactive API. Run the tests with:

```bash
python -m unittest discover -s backend/tests -t .   # backend
python -m unittest discover -s tests -t .           # AI pipeline
```

## Repository layout

| Path | Contents |
|---|---|
| `ai/` | AI pipeline: ingestion, chunking, embeddings, vector store, retrieval, answering |
| `backend/` | FastAPI application, migrations and backend tests ([`backend/README.md`](backend/README.md) lists every endpoint) |
| `tests/` | AI-pipeline tests |
| `evaluation/` | offline retrieval and answer evaluation harnesses |
| `docs/` | architecture, security contract, release gates, plans |

## Documentation

| Start here | |
|---|---|
| [`docs/SYSTEM_OVERVIEW.md`](docs/SYSTEM_OVERVIEW.md) | one-page summary |
| [`docs/BACKEND_ARCHITECTURE_FINAL.md`](docs/BACKEND_ARCHITECTURE_FINAL.md) | architecture, flows, data model, security, CI history |
| [`docs/SECURITY_EXECUTIVE_SUMMARY.md`](docs/SECURITY_EXECUTIVE_SUMMARY.md) | security verdict in plain language |
| [`docs/PROJECT_TIMELINE.md`](docs/PROJECT_TIMELINE.md) | how the project progressed |
| [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) | the live demo |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | engineering process and rules |

Detailed records: [`docs/backend_security_contract.md`](docs/backend_security_contract.md),
[`docs/SECURITY_VERIFICATION.md`](docs/SECURITY_VERIFICATION.md), the release gates in `docs/`, and
[`docs/RELEASE_READINESS_PLAN.md`](docs/RELEASE_READINESS_PLAN.md).

## Status and next steps

- **Done:** backend vertical slice: accounts, courses, upload and processing, grounded chat, summaries, quiz generation,
  quiz taking (M0-M5).
- **Frontend** (`frontend/`, Next.js): milestones F0 (accounts, dashboard, courses, uploads) and F1 (grounded
  summaries and chat) are complete with green CI; F2 (quizzes, attempts and review) is implemented and awaiting CI
  ([`frontend/README.md`](frontend/README.md), gates `docs/F0A_GATE.md` … `docs/F2_GATE.md`).
- **Before production or public use:** HTTPS and deployment hardening, a privacy notice and consent for the external AI
  provider, account deletion ([`docs/RELEASE_READINESS_PLAN.md`](docs/RELEASE_READINESS_PLAN.md)).

Built by the IntelliStudy team; backend and AI pipeline led by Mohamed Amir Kamal; supervised by Prof. Gamal Ebrahim.

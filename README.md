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
- **Security by contract:** a written security contract, enforced by **298 release-gate tests** across milestones
  M1-M5 (approved 2026-11-25) and an OWASP Top 10 / OWASP Top 10 for LLM Applications review with no open item.
- **Tested on every push:** backend tests, AI-pipeline tests, frontend unit and end-to-end tests, ruff, mypy, gitleaks
  and pip-audit. Local run on 2026-11-28: 417 backend, 800 AI-pipeline (12 skipped, 1 expected failure), 268 Vitest
  and 46 Playwright tests, all passing.

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

## Status

- **Done:** backend vertical slice: accounts, courses, upload and processing, grounded chat, summaries, quiz generation,
  quiz taking (M0-M5). Since then: combined summaries of several documents (migration 0008) and a database-schema
  check at startup (`/health` reports an outdated schema).
- **Frontend** (`frontend/`, Next.js): milestones F0 (accounts, dashboard, courses, uploads) and F1 (grounded
  summaries and chat) are complete with green CI. F2 (quizzes, attempts and review) is implemented; its gate
  ([`docs/F2_GATE.md`](docs/F2_GATE.md)) still records the CI item GF2-29 as open and has no sign-off. Also built:
  uploading several files at once, and summaries and quizzes from files selected in the Course Workspace
  ([`frontend/README.md`](frontend/README.md), gates `docs/F0A_GATE.md` … `docs/F2_GATE.md`).
- **Before production or public use:** HTTPS and deployment hardening, a privacy notice and consent for the external AI
  provider, account deletion ([`docs/RELEASE_READINESS_PLAN.md`](docs/RELEASE_READINESS_PLAN.md)). These gates
  apply whatever the feature roadmap below delivers.

## Roadmap

This section is the single roadmap reference. Other documents link here and don't repeat it. The four sprints run in
this order. Nothing in them is approved work beyond what the status says: estimates, models and limits are listed only
where they are decided, and none are decided yet.

Status key: **Exists** means built and tested today. **Partial** means some of it exists, and the note says what.
**Not started** means nothing exists yet.

### Sprint 1: Security and resilience

Scope: an authorized, defensive assessment of the local system only. All tests are non-destructive and run on an
isolated local stack with its own test database; no external system or third-party service is tested.

| Item | Status | What exists today, and what is missing |
|---|---|---|
| Threat model | Partial | [`docs/backend_security_contract.md`](docs/backend_security_contract.md) sets threat priorities (P0 cross-user leakage and IDOR first) and traces rules to threats (Appendix A). An OWASP Top 10 and LLM Top 10 review is in [`docs/SECURITY_VERIFICATION.md`](docs/SECURITY_VERIFICATION.md). Missing: the Next.js frontend and its proxy, and the features added after M5 (combined summaries, multi-file selection). |
| Authorization matrix | Partial | The ownership model and isolation rules are in the contract. Route-wide cross-user tests are in `backend/tests/test_g5_security.py`. Missing: a single route-by-role table (roles: student and admin; an admin can't read student data). |
| Upload and proxy authentication order | Not started | The Next.js upload proxy accepts a body of up to 101 MiB before the backend checks authentication. The backend itself streams uploads and stops at its limit. |
| Course, conversation and retry limits | Not started | Today: login lockout, a daily token budget per user, and at most 5 queued processing jobs per user. Not limited: creating courses and conversations, and retrying a failed document (beyond the 5-job queue). |
| Rate limiting | Exists (single process) | An in-process limiter covers login, registration, refresh, upload, chat, summaries, quizzes and attempts, and answers 429 with `Retry-After`. A shared store for several processes is an R1 item. |
| Atomic generation deduplication | Partial | Generation runs on one background runner. A summary request reuses a running job for the same document, or an identical in-flight combined summary, but the check and the insert are separate steps, so two concurrent requests can both create a job. Missing: an atomic check, and a per-user cap on concurrent generation. |
| CSP and security headers | Partial | The backend sends `nosniff`, `no-referrer`, `X-Frame-Options: DENY` and a strict CSP (`backend/app/core/middleware.py`). The frontend sends the same first three plus a `Permissions-Policy` (`frontend/next.config.ts`), but no Content Security Policy; CSP is planned in frontend milestone F4. HSTS belongs to the deployment (R1). |
| ZIP-bomb and parser defenses | Exists | Built in M2: file type checked by content, decompression and entry-count limits, path-traversal and macro detection, and parsing in a sandbox with CPU, memory and time limits (`backend/tests/test_g2_upload.py`). |
| Security regression tests | Exists for the backend | The 298 M1-M5 release-gate tests (`backend/tests/test_g1_*` … `test_g5_*`), 15 combined-summary tests (`test_g6_*`, no gate document) and a static-rule meta-test run in CI. Sprint 1 adds a test for each new finding. |
| Controlled load baseline | Not started | Planned with Locust or k6 against the isolated stack, in steps (for example 1, 10, 25, 50 users), with AI calls served by the deterministic test provider. No scripts or results exist; the only performance figures are the single-user timings above. |
| Before/after report | Not started | Needs the load baseline and the fixes above. |

### Sprint 2: Mastery data model

Scope: a backend model of what each student knows per topic, built from quiz attempts, that can say how sure it is.

| Item | Status | What exists today, and what is missing |
|---|---|---|
| Topic taxonomy strategy | Not started | Each generated question carries a short topic name written by the model (1-80 characters). No topics are extracted from documents and there is no course taxonomy. The strategy (extracted, model-proposed, or fixed per course) is undecided. |
| Question-to-topic mapping | Partial | One topic string is stored per question and grouped case- and space-insensitively. Missing: mapping to taxonomy topics, so a topic is recognised across quizzes. |
| Mastery events | Not started | Attempts, answers and grading results are stored and could feed events. No event record exists. |
| Evidence count | Not started | |
| Confidence | Not started | |
| Recency and consistency | Not started | |
| Explainable scoring | Partial | Attempt results include a score per topic for that attempt (`topics` in the results response). No score combines attempts, and no explanation of a score exists. |
| API endpoints | Not started | No mastery routes exist. |
| Migration and tests | Not started | The latest migration is 0008 (combined summaries). |

### Sprint 3: Adaptive learning UX

Scope: show students their mastery and let them practise weak topics. **Blocked** until Sprint 2 is complete and the
T-6 successor decision, [T-7](docs/TEAM_DECISION_T-7.md) (status: Proposed), is accepted. Under T-7, personalized
quizzes are formative practice only: they never change an official grade, a normal quiz stays available, and adaptive
high-stakes exams stay out of scope. This is frontend milestone F5 in
[`docs/FRONTEND_IMPLEMENTATION_PLAN.md`](docs/FRONTEND_IMPLEMENTATION_PLAN.md).

| Item | Status | What exists today, and what is missing |
|---|---|---|
| Mastery dashboard | Not started | The Dashboard deliberately hides the "weakest topics" and recommendation rows, because there is no data for them. A topic with too little evidence must show "not enough evidence yet", never a score (T-7). |
| Weak-topic review | Not started | |
| Normal quiz remains available | Exists | Today's quiz from selected files, and "Retry wrong answers", stay as they are. |
| Personalized practice quiz | Not started | Needs T-7 accepted and Sprint 2 done. |
| New question allocation | Not started | Quiz generation takes a question count and source documents only. |
| Explanation for topic selection | Not started | Required by T-7: the student sees why each topic was chosen. |
| Source citations | Exists for today's quizzes | Every question is validated against quoted evidence; the review shows the explanation, the evidence and its cited source. Practice quizzes must keep this. |
| Progress after each attempt | Partial | Results show the score, the per-topic score for that attempt and the quiz's attempt history. Missing: progress across attempts and quizzes. |

### Sprint 4: Audio MVP

Scope: study from recorded lectures as well as documents. Nothing audio-related exists; uploads accept PDF, PPTX and
DOCX only.

| Item | Status | Notes |
|---|---|---|
| Audio upload and validation (MP3, WAV, M4A) | Not started | Would extend the content-checked upload path. Duration and size limits are not set; they are to be decided from measurement. |
| Asynchronous transcription | Not started | A background job, like document processing. The transcription model and its runtime (local or hosted) are an open decision. If audio is sent to an external provider, the P1 privacy consent is required before any non-team user. |
| Timestamped transcript | Not started | |
| Indexing into summary, chat and quiz flows | Not started | Would reuse chunking, embeddings and the course-scoped vector store. |
| Timestamp citations and audio player | Not started | Citations today point to pages and slides. |

Built by the IntelliStudy team; backend and AI pipeline led by Mohamed Amir Kamal; supervised by Prof. Gamal Ebrahim.

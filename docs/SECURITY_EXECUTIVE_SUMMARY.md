# IntelliStudy Backend: Executive Security Summary

**Date:** 2026-11-25. **Scope:** the backend vertical slice (accounts, courses, document upload and processing, grounded
chat, summaries, quiz generation, quiz taking), milestones M0-M5. **Evidence:** CI run #9 on commit `d990509`, all
jobs green. Full record: [`SECURITY_VERIFICATION.md`](SECURITY_VERIFICATION.md). Rules:
[`backend_security_contract.md`](backend_security_contract.md) v1.10.

## Verdict

The backend meets its security contract for a **team demo on a local machine**. Every security requirement has passing
automated tests, and no known issue blocks the demo. Two kinds of work remain before the system is opened to people
**outside the team** or deployed to the **cloud** (see "Before wider use" below).

## What is protected, and how we know

| Risk | Protection | Proof |
|---|---|---|
| One student seeing another student's data | Every request is checked against the owner. A foreign resource looks exactly like a missing one. Search, summaries and quizzes only ever read the student's own, fully processed documents. | Automated checks call **every** API route as a different user, and with random and malformed ids. A route added later without these checks fails the build. |
| Quiz answers leaking before submission | Answer keys are stored apart from questions. Saving an answer never says whether it is right. Answers appear only in the results of a submitted attempt. | Tests scan every response; a static check proves only the grading code reads the keys. |
| Tampering with scores | Grading happens on the server without any AI model. Submitted attempts can never be changed. Clients cannot send scores or times. | Tests include two submissions racing each other and a save racing a submission. |
| Stolen or misused logins | Strong password hashing, short-lived tokens, refresh-token rotation with reuse detection, account lockout after repeated failures. | 79 tests in the first gate (M1). |
| Malicious uploaded files | File type checked by content, size, page and decompression limits, parsing in an isolated process with time and memory limits. | 39 tests in the M2 gate. |
| Malicious instructions hidden in documents ("prompt injection") | Documents are treated as untrusted data; every answer sentence must cite and match the student's material; quiz answers are checked against quoted evidence. | Injection tests in M3, M4 and M5. |
| Runaway AI cost | Per-user rate limits and a daily token budget recorded in a ledger that deleting content never refunds. | Budget tests in M3 and M4. |
| Leaked secrets | Keys only in environment variables, never in the repository, logs or responses. | Secret scanning (gitleaks) and log-redaction tests on every build. |

**In numbers** (at M5 approval, 2026-11-25): 298 release-gate checks across five milestones (each one an automated test), 402 backend tests and
800 AI-pipeline tests passing in CI; all 70 rows of the contract's security test matrix mapped to tests; the OWASP Top
10 and OWASP Top 10 for LLM Applications reviewed with **no open item**. Critical controls were proven by removing them
one at a time and confirming the tests fail (11 for M5 alone).

## Accepted risks (known, recorded, not blocking the demo)

| Id | Risk in plain terms |
|---|---|
| F-M3-03 | An AI model that follows a document's own instructions can still repeat that document's text with a valid citation. It cannot reach other students' data. |
| F-M4-02 | Quiz questions are checked by comparing words, not meaning, so a subtly wrong question can occasionally pass. Students will be able to flag such questions later. |
| F-M4-03 | AI-generated text must be shown as plain text by the future frontend. |
| F-M4-07 | Some PDFs store hyphenated words split in two, which slightly weakens search and grounding for those files. This affects quality, not security. |
| F-M5-02 | Document text is sent to an external AI provider (DeepSeek) to answer questions and write summaries and quizzes. |
| F-M5-03 | Encrypted connections (HTTPS), alerting and shared rate limits are properties of a cloud deployment and do not exist in the local demo. |

## Before wider use

| Before... | Required | Owner | Milestone |
|---|---|---|---|
| any production deployment | HTTPS with HSTS, client addresses behind the proxy, a shared rate-limit store, alerting, backups, cloud CORS origins and secret management (F-M5-03, F-M2-13); the frontend shows AI text as plain text (F-M4-03, upgraded to a blocker) | Mohamed Amir Kamal (deployment); Frontend Team (rendering) | R1 |
| any non-team user uploads a document | A privacy notice and consent recorded by the server, the AI provider's data terms reviewed, supervisor approval (F-M5-02); account deletion | Mohamed Amir Kamal; approval by Prof. Gamal Ebrahim | P1 |
| later quality work | Repair split words at ingestion (F-M4-07); fewer dropped quiz questions and question flagging (F-M4-02) | Mohamed Amir Kamal | M6 |

Owners and milestones confirmed 2026-11-25 in [`RELEASE_READINESS_PLAN.md`](RELEASE_READINESS_PLAN.md). Planned
security work beyond these gates (threat model update, authorization matrix, abuse and concurrency limits, a load
baseline) is Sprint 1 in the [`README.md` roadmap](../README.md#roadmap). Its fixes are not made yet.

## Status

**M5 approved 2026-11-25.** The OWASP review is signed off, the manual demo with the real AI provider met every target
(M5 gate section 2.11), and owners are confirmed.

# Release Readiness Plan (after M5)

**Status:** approved 2026-11-25 as written (groups A-D accepted; owners confirmed below). No implementation yet: R1, P1
and M6 start only on the team's instruction.
**Authority:** [`backend_security_contract.md`](backend_security_contract.md) v1.10 (Appendix B, Appendix D, 9a, HTTP-01,
UPL-15, 10.7); [`SECURITY_VERIFICATION.md`](SECURITY_VERIFICATION.md); [`M5_RELEASE_GATE.md`](M5_RELEASE_GATE.md).

## 1. Categories

| Group | Meaning |
|---|---|
| **A** | Must be completed before any production (cloud, network-reachable) deployment |
| **B** | Must be completed before public / non-team users are allowed |
| **C** | Recommended for M6 |
| **D** | Future enhancement / accepted residual risk |

Owners (confirmed 2026-11-25):

| Role | Owner |
|---|---|
| Backend lead (project owner) | Mohamed Amir Kamal |
| AI pipeline owner | Mohamed Amir Kamal |
| Deployment owner | Mohamed Amir Kamal |
| Frontend lead | Frontend Team (until assigned) |
| Supervisor (review and approval) | Prof. Gamal Ebrahim |

## 2. Classification

| Item | Group | Reason | Impact | Contract allows release unresolved? | Owner | Target |
|---|---|---|---|---|---|---|
| **F-M5-03 / deployment tasks**: HTTPS + HSTS, alerting on the security log, cloud CORS origins, JWT secret in a secret manager with rotation, backups | A | HTTP-01 is a MUST for cloud deployments; Appendix B lists CORS origins and JWT key management as "before cloud deployment" | Security: tokens and refresh cookies in clear text without TLS; no detection of attacks without alerting. Reliability: no recovery without backups | Local demo: yes. Cloud: **no** | Deployment owner, with backend lead | R1 (deployment readiness), before the first cloud deployment |
| **Shared rate-limiter store + trusted-proxy client IP** (9a, F-M2-13) | A | 9a: a multi-process or multi-instance deployment MUST use a shared store. Behind a TLS proxy, every client shares the proxy's address unless trusted-proxy handling exists | Security: per-IP login limits and lockout collapse into one bucket. One attacker can lock everyone out, or brute-force limits stop being per-attacker. Reliability: per-worker limits multiply the real limit | Single process, no proxy: yes. Multi-worker or behind a proxy: **no** | Deployment owner, with backend lead | R1 |
| **F-M4-03**: quiz text is untrusted model output; **the rendering half of F-M3-03** | A (**upgraded**, see section 3) | UPL-15 is a MUST: the frontend renders model output as escaped text or sanitised Markdown. Today no frontend exists, so the rule is untested | Security: stored XSS from a crafted lecture file. Text the model repeats from a document (F-M3-03) or puts into a quiz (F-M4-03) could run script in the student's browser. That exposes the in-memory access token and lets the attacker act as the student | Backend-only release: yes. Any release with a web frontend: **no** | Frontend lead, reviewed by backend lead | Frontend milestone; verified in R1 |
| **F-M5-02 / privacy notice**: document content is sent to DeepSeek | B | Appendix B: "before any non-team user uploads" | Privacy and compliance: lecture files can contain personal data (names, student ids). The content leaves the system for a third-party provider abroad. Egypt's data-protection law (Law 151/2020) and university policy may apply; this needs supervisor or legal review, and this plan is not legal advice | Team use: yes. Non-team users: **no** | Backend lead (consent record), frontend lead (notice UI), supervisor (approval) | P1 (public readiness), before the first non-team account |
| **F-M4-07**: soft hyphens split words at ingestion | C | Quality, not security (the finding says so). The fix touches stored chunks, embeddings and the calibrated retrieval policy, so it needs its own change with the retrieval evaluation re-run | Reliability and quality: on such PDFs, grounding can remove correct sentences and lexical retrieval misses words. Quiz evidence is already handled (F-M4-06) | **Yes** | AI pipeline owner | M6 (first item) |
| **F-M4-02**: quiz validation is lexical, not semantic | C | Accepted by design (T-6: no LLM judge). Two cheap mitigations fit M6: a prompt asking for distractors the evidence does not name (raises yield without weakening QAV-04), and question flagging (FR-EXM-11) | Quality and misinformation: a subtly wrong question can occasionally pass. Measured: 5/5 and 10/10 keys correct in manual runs | **Yes** (LLM09, signed as residual) | AI pipeline owner (prompt), backend lead (flagging) | M6 |
| **F-M3-03**: an obedient model can repeat a document's own text with a valid citation | D | Harm is bounded to the uploader's own content in the uploader's own course (scoped retrieval, G3-PI-05). The rendering risk is covered by the F-M4-03 row above | Security: low once UPL-15 holds; no cross-user reach | **Yes** (LLM01, signed as residual) | Backend lead (monitor) | Accepted; revisit if documents become shareable between users |

## 3. Upgrades

**F-M4-03 and the rendering half of F-M3-03 become production blockers (group A).** Both were accepted on one
condition: that the frontend renders model output as text (UPL-15). That condition cannot be checked while no frontend
exists, and the first frontend release is exactly when it starts to matter. Minimum work before production:

1. **Rendering:** all model text (chat answers, summaries, quiz stems, options, topics, rationales, evidence) is
   rendered as escaped text or through a Markdown renderer with raw HTML disabled and links restricted to
   `http(s)` / in-app citation anchors.
2. **CSP:** the deployed frontend sends a Content-Security-Policy without `unsafe-inline` scripts.
3. **Proof:** one automated frontend test uploads, or mocks, a document whose text contains
   `<script>`, `<img src=x onerror=...>` and `[x](javascript:...)`, and proves each is rendered inert in chat, summary,
   quiz and results views.

**F-M2-13 (trusted-proxy client IP) is a production blocker**, not only a "deployment property". TLS normally ends at a
reverse proxy (group A). Behind it, every request appears to come from the proxy's address, so the per-IP login limit
and the lockout protections stop working: one client can lock every user out. Minimum work: derive the client address
from `X-Forwarded-For` only through a configured list of trusted proxy hops, and test that a spoofed header from an
untrusted peer is ignored.

**No upgrade for F-M5-02.** Group B is right: the risk arises when people outside the team upload. Its minimum
work, though, is more than a text notice:
- consent recorded server-side (version and time) and checked before any upload or model call;
- the provider's data-retention and training terms reviewed and summarised in the notice;
- supervisor approval.

## 4. Found during this review (not in the original list)

| Item | Group | Why |
|---|---|---|
| Deployment topology: SQLite and embedded Chroma are single-process | A (decision) | Either deploy one worker (the in-process limiter stays valid) or move to PostgreSQL, a Chroma server and the shared limiter. The choice must be recorded before R1 |
| Account deletion (FR-AUTH-10, ISO-10 "when implemented") and a data-retention statement | B | Public users need a way to delete their account and all data. Today they can delete courses and documents, not the account |
| Incident response for leaked secrets (SEC-10) rehearsed once in the deployed environment | A | The rule exists; the procedure is untested outside local runs |

## 5. Prioritised roadmap

1. **M5 closeout (now, no code).** Owner sign-off of `SECURITY_VERIFICATION.md` sections 3-4; owners and dates
   confirmed; this plan accepted; M5 marked approved.
2. **R1: production readiness (group A), before any cloud deployment.**
   1. Record the topology decision: one worker, or PostgreSQL + Chroma server + Redis.
   2. TLS at the proxy, HSTS, HTTP redirect; trusted-proxy client IP (F-M2-13).
   3. Shared rate-limiter store if more than one process.
   4. Cloud CORS origins; JWT secret in a secret manager with a rotation plan; SEC-10 rehearsal.
   5. Alerting on security events (lockouts, refresh reuse, ownership mismatches, tripwires); database and vector
      store backups with one restore test.
   6. Frontend UPL-15 verification (section 3), as soon as a frontend exists.
3. **P1: public readiness (group B), before the first non-team account.** It can run in parallel with R1.
   1. Privacy notice and consent recorded server-side, plus the provider-terms review and supervisor approval (F-M5-02).
   2. Account deletion and a retention statement.
4. **M6 (group C).** Fix F-M4-07 at ingestion and reprocess, with the retrieval evaluation re-run. Change the quiz
   prompt so distractors are not named in the evidence. Add question flagging (FR-EXM-11), which also mitigates
   F-M4-02.
5. **Future (group D).** F-M3-03 stays accepted, and is revisited if sharing between users is ever added. Semantic
   question validation would need T-6 to be reopened (no LLM judge today).

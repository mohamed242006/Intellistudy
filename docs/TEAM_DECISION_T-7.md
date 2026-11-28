# Team decision T-7: personalized practice quizzes (amends T-6)

| | |
|---|---|
| **Status** | **Proposed**, 2026-11-28. Not accepted. Under [`CONTRIBUTING.md`](../CONTRIBUTING.md) the team approves decisions; until it does, T-6 applies unchanged. |
| **Amends** | T-6, team decision of 2026-11-24 ([`M4_RELEASE_GATE.md`](M4_RELEASE_GATE.md) section 1.2, restated in [`M5_RELEASE_GATE.md`](M5_RELEASE_GATE.md) section 1.2) |
| **Affects** | Sprint 3 (adaptive learning UX) in the [`README.md` roadmap](../README.md#roadmap); frontend milestone F5 ([`FRONTEND_IMPLEMENTATION_PLAN.md`](FRONTEND_IMPLEMENTATION_PLAN.md)) |
| **Recorded by** | project owner, as a proposal for the team |

## Context

T-6 reads: "Excluded: short-answer questions, essay questions, adaptive exams, LLM-based grading. Question validation
in M4 is deterministic (no LLM judge). Quiz taking and grading are M5."

T-6 set the scope of the backend slice, M4 and M5. The roadmap's Sprint 3 includes personalized quizzes on a
student's weak topics. Under T-6, read literally, these could count as "adaptive exams". T-7 separates formative
practice from assessment, so Sprint 3 can be planned without reopening the rest of T-6.

## Decision (proposed)

1. **Unchanged from T-6:** adaptive high-stakes exams stay out of scope. So do short-answer and essay questions, and
   LLM-based grading. Question validation stays deterministic.
2. **New:** personalized *practice* quizzes may be added. Work starts only after the Sprint 2 mastery infrastructure
   exists.
3. They are formative practice, not graded high-stakes assessment, and they never change an official grade or an
   existing quiz result.
4. A student can always choose a normal, non-personalized quiz instead.
5. Topic selection is explainable. The student sees why each topic was chosen, for example from which attempts and
   with how much evidence.
6. Source citations and grounding stay required, exactly as for today's quizzes: every question must be validated
   against quoted evidence from the student's own documents.
7. Where there is too little evidence for a topic, the system says so ("not enough evidence yet"). It never shows an
   invented or confident-looking mastery score.
8. **Precondition:** personalization does not begin until all of these are implemented and tested:
   - the mastery model (Sprint 2);
   - its confidence and evidence rules;
   - the privacy requirements, including P1 in [`RELEASE_READINESS_PLAN.md`](RELEASE_READINESS_PLAN.md) before any
     non-team user.

## Rationale

- Practice that targets weak topics is the main learning benefit of a mastery model. Formative use carries low risk,
  because nothing official depends on it.
- The risks that T-6 guarded against stay excluded: ungrounded questions, AI-judged answers, and assessments that
  change outcomes.
- Requiring an evidence threshold and an explanation keeps the system honest about uncertainty. A mastery number
  built on one or two answers would mislead students.

## Consequences

- Sprint 3's personalized practice quiz stays blocked until T-7 is accepted *and* Sprint 2 is complete.
- The rest of Sprint 3 depends on Sprint 2 only: the mastery dashboard, weak-topic review and progress views. These
  are not affected by T-6.
- The exam builder and exam result screens (UI frame 09) stay out of scope.
- If the team rejects T-7, T-6 stands and the Sprint 3 personalized quiz item is removed from the roadmap.

## History

| Date | Change |
|---|---|
| 2026-11-24 | T-6 recorded as a team decision (M4 gate). |
| 2026-11-28 | T-7 proposed as an amendment to T-6. Status: Proposed. |

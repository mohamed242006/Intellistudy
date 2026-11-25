# IntelliStudy: Live Demo Script (about 15 minutes)

**For:** the presenter at a graduation-project review. Each step has what to **say** and what to **do**. All commands
run in one terminal and were taken from the recorded demo run ([`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md), M5 gate section
2.11). Paste each block whole.

## Before the session (10 minutes, not shown)

1. `.env` has a real `INTELLISTUDY_DEEPSEEK_API_KEY`. Start the server in a second terminal and leave it running:

   ```bash
   cd ~/Downloads/Intellistudy-project/Intellistudy && source .venv/bin/activate
   python -m backend.app.db.migrate
   uvicorn --factory backend.app.main:create_app --host 127.0.0.1 --port 8000 2>&1 | tee ~/demo_run.log
   ```

2. In the demo terminal, define the helpers (from the repository root, with `.venv` active):

   ```bash
   BASE=http://127.0.0.1:8000/api/v1
   reg()   { curl -s -X POST $BASE/auth/register -H 'Content-Type: application/json' -d "{\"email\":\"$1\",\"name\":\"$2\",\"password\":\"Demo-student-2026\"}" > /dev/null; }
   tok()   { curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' -d "{\"email\":\"$1\",\"password\":\"Demo-student-2026\"}" | jq -r .access_token; }
   STAMP=$(date +%s); A=alice.$STAMP@example.com; B=bob.$STAMP@example.com
   reg $A Alice; reg $B Bob
   AUTH="Authorization: Bearer $(tok $A)"; BAUTH="Authorization: Bearer $(tok $B)"
   ```

3. Have the backup material open in a browser tab: the green CI run, [`SECURITY_VERIFICATION.md`](SECURITY_VERIFICATION.md)
   and M5 gate section 2.11 (the recorded demo numbers).

Tokens last 15 minutes. If a call returns 401, rerun the `AUTH=` / `BAUTH=` line.

---

## 1. The problem (1 minute, slides or talk)

**Say:** "Students study from long slides. General chatbots answer from the internet and invent facts. IntelliStudy
answers only from the student's own lectures, shows the page it used, and refuses when the lecture does not say."

## 2. Upload a lecture (2 minutes)

**Do:**
```bash
COURSE=$(curl -s -X POST $BASE/courses -H "$AUTH" -H 'Content-Type: application/json' -d '{"name":"Software Engineering"}' | jq -r .id)
curl -s -X POST $BASE/courses/$COURSE/documents -H "$AUTH" -F "files=@data/uploads/Lecture1.pdf" -F "files=@data/uploads/Lecture2.pptx" | jq '[.documents[] | {file_name, status}]'
until [ "$(curl -s $BASE/courses/$COURSE/documents -H "$AUTH" | jq '[.items[] | select(.status != "ready" and .status != "failed")] | length')" = 0 ]; do curl -s $BASE/courses/$COURSE/documents -H "$AUTH" | jq -c '[.items[] | {file_name, status, progress}]'; sleep 3; done
curl -s $BASE/courses/$COURSE/documents -H "$AUTH" | jq '[.items[] | {file_name, status, page_count, chunk_count}]'
DOC=$(curl -s $BASE/courses/$COURSE/documents -H "$AUTH" | jq -r '.items[] | select(.file_name=="Lecture1.pdf") | .id')
```

**Say while it runs:** "Each file is checked by its content, not its extension, and parsed in a separate process that
has no access to secrets and has memory and time limits. The statuses you see are extracting, embedding and indexing.
A document can be searched only once it is ready." (Recorded: 44-page PDF in 10.4 s.)

## 3. Grounded chat (2 minutes)

**Do:**
```bash
CONV=$(curl -s -X POST $BASE/courses/$COURSE/conversations -H "$AUTH" -H 'Content-Type: application/json' -d '{}' | jq -r .id)
ask() { curl -s -X POST $BASE/conversations/$CONV/messages -H "$AUTH" -H 'Content-Type: application/json' -d "{\"question\":\"$1\"}" | jq '{state, refusal_reason, text, citations: [.citations[] | .citation_label]}'; }
ask "Why did component-based software engineering emerge?"
ask "Who won the 2022 football World Cup?"
```

**Say:** "The first answer cites page 3 of the lecture. Every sentence was checked against that passage. The second
question is not in the lecture, so the system refuses instead of guessing, and the model is never called for it."

## 4. Summary (1.5 minutes)

**Do:**
```bash
curl -s -X POST $BASE/documents/$DOC/summary -H "$AUTH" -H 'Content-Type: application/json' -d '{}' | jq .status
until [ "$(curl -s $BASE/documents/$DOC/summary -H "$AUTH" | jq -r .status)" != generating ]; do sleep 2; done
curl -s $BASE/documents/$DOC/summary -H "$AUTH" | jq '{grounding, first_sections: [.sections[:3][] | {heading, source_range, text}]}'
```

**Say:** "Each section shows its page range and numbered citations. `grounding` shows how many sentences were checked
and how many unsupported ones were removed before the student sees the summary."

## 5. Quiz generation (2 minutes)

**Do:**
```bash
QUIZ=$(curl -s -X POST $BASE/courses/$COURSE/quizzes -H "$AUTH" -H 'Content-Type: application/json' -d '{"question_count":10}' | jq -r .id)
until [ "$(curl -s $BASE/quizzes/$QUIZ -H "$AUTH" | jq -r .status)" != generating ]; do sleep 2; done
curl -s $BASE/quizzes/$QUIZ -H "$AUTH" | jq '{status, question_count, first_question: .questions[0]}'
grep '"quiz job' ~/demo_run.log | tail -1 | jq -r .message
```

**Say:** "Ten questions in under 45 seconds (recorded: 18.1 s). The model proposed more; the log shows how many were
dropped and why. A question is kept only if its answer is proven by a quote from the lecture and no wrong option could
also be right. Notice what the quiz does **not** contain: the correct answer. Answer keys never leave the server
before submission."

## 6. Take the quiz (3 minutes)

**Do** (answers by position: `choice` 0-3 for multiple choice; for true/false, 0 means true and 1 means false):
```bash
ATTEMPT=$(curl -s -X POST $BASE/quizzes/$QUIZ/attempts -H "$AUTH" | tee /tmp/attempt.json | jq -r .id)
jq -r '.questions[] | "\(.position). [\(.type)] \(.stem)\n   \(.options // ["true","false"] | to_entries | map("\(.key): \(.value)") | join("   "))"' /tmp/attempt.json
answer() { Q=$(jq -r ".questions[$(($1-1))] | .id" /tmp/attempt.json); T=$(jq -r ".questions[$(($1-1))] | .type" /tmp/attempt.json); if [ "$T" = mcq ]; then B="{\"choice\": $2}"; else B="{\"value\": $([ "$2" = 0 ] && echo true || echo false)}"; fi; curl -s -o /dev/null -w "Q$1: %{http_code} in %{time_total}s\n" -X PUT $BASE/attempts/$ATTEMPT/answers/$Q -H "$AUTH" -H 'Content-Type: application/json' -d "$B"; }
```

Ask the panel to choose a few answers, then call `answer <position> <option>` for each, for example:
```bash
answer 1 0; answer 2 2; answer 3 1
```

**Say:** "Each answer is saved immediately, in a few milliseconds, and the response never says whether it was right.
The student can close the laptop and resume later."

**Do:**
```bash
curl -s -X POST $BASE/attempts/$ATTEMPT/submit -H "$AUTH" -o /tmp/results.json -w 'graded in %{time_total}s\n'
jq '{score, max_score, percent, topics}' /tmp/results.json
jq '.questions[] | select(.correct | not) | {position, correct_answer, evidence, citation: .citation.citation_label}' /tmp/results.json | head -40
curl -s -X POST $BASE/attempts/$ATTEMPT/retry-missed -H "$AUTH" | jq '{question_count, questions: [.questions[].position]}'
```

**Say:** "Grading takes about 10 ms and uses no AI. For every mistake the student sees the correct answer, the exact
sentence from the lecture that proves it, and the page to review. Retry creates a new attempt with only the missed
questions. The submitted attempt can never be changed."

## 7. Security in action (2 minutes)

**Do:**
```bash
for url in courses/$COURSE documents/$DOC/summary quizzes/$QUIZ attempts/$ATTEMPT/results; do curl -s -o /dev/null -w "Bob -> $url: %{http_code}\n" $BASE/$url -H "$BAUTH"; done
curl -s -o /dev/null -w "Bob -> random id: %{http_code}\n" $BASE/quizzes/00000000-0000-4000-8000-000000000000 -H "$BAUTH"
curl -s -o /dev/null -w "No token: %{http_code}\n" $BASE/quizzes/$QUIZ
```

**Say:** "Bob gets exactly the same 404 for Alice's data as for an id that does not exist, so he cannot even tell that
it exists, and the attempt is logged as a security event. Without a token, every route answers with the same 401.
These checks run automatically against **every** route on every commit: 298 release-gate tests, plus a signed-off
OWASP review."

## 8. Close (1 minute)

**Say:** "Backend milestones M0 to M5 are complete, every one gated by automated tests and a green CI run. Next come
production hardening (HTTPS, rate limits behind a proxy), a privacy notice for the AI provider, and the frontend."

Show the CI page and [`SYSTEM_OVERVIEW.md`](SYSTEM_OVERVIEW.md) if time allows.

---

## If something goes wrong

| Problem | Recovery |
|---|---|
| 401 on any call | rerun the `AUTH=` / `BAUTH=` line (tokens last 15 minutes) |
| A model call is slow or `llm_unavailable` | say "the provider is unavailable, and the system refuses instead of failing". Show M5 gate section 2.11 (recorded run). Quiz taking still works without the model |
| Quiz has fewer than 10 questions | expected behaviour: the notice explains that the material supported fewer good questions |
| Server not responding | restart it (terminal 2); data persists in `data/backend/` |

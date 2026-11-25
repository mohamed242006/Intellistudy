# Demo Runbook: the Backend Vertical Slice with DeepSeek

**Purpose:** the manual demo run required by the M5 gate ([`M5_RELEASE_GATE.md`](M5_RELEASE_GATE.md), section 3): one
student goes from upload to quiz results and a retry on real lecture files, through the HTTP API, with the real
DeepSeek provider. The run is recorded **without document content**: timings, counts, tokens and statuses only.

The automated version of the same flow, with a scripted model, is G5-E2E-01 (`backend/tests/test_g5_e2e.py`).

## 0. Prerequisites

- Repository root, project `.venv` active (Python 3.12, `requirements.lock.txt`).
- `.env` from `.env.example` with a real `INTELLISTUDY_JWT_SECRET` and `INTELLISTUDY_DEEPSEEK_API_KEY`. `.env` is
  git-ignored and is never committed.
- Two or three real lecture files (PDF or PPTX); at least one PDF of 30 pages or more.
- `curl` and `jq`.

## 1. Start the server with its log captured

```bash
python -m backend.app.db.migrate
uvicorn --factory backend.app.main:create_app --host 127.0.0.1 --port 8000 2>&1 | tee ~/demo_run.log
```

In a second terminal:

```bash
BASE=http://127.0.0.1:8000/api/v1
EMAIL=demo.student@example.com; PASS='Demo-student-2026'
curl -s -X POST $BASE/auth/register -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"name\":\"Demo student\",\"password\":\"$PASS\"}" | jq '{id, email}'
login() { TOKEN=$(curl -s -X POST $BASE/auth/login -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" | jq -r .access_token); AUTH="Authorization: Bearer $TOKEN"; }
login   # the access token lasts 15 minutes: run `login` again whenever a call returns 401
```

## 2. Course and upload (NFR-PER-04: a 50-page text PDF ready in under 90 s)

```bash
COURSE=$(curl -s -X POST $BASE/courses -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Demo course"}' | jq -r .id)
T0=$(date +%s.%N)
curl -s -X POST $BASE/courses/$COURSE/documents -H "$AUTH" \
  -F "files=@/path/to/lecture1.pdf" -F "files=@/path/to/lecture2.pptx" | jq '[.documents[] | {id, file_name, status}]'
until [ "$(curl -s $BASE/courses/$COURSE/documents -H "$AUTH" | jq '[.items[] | select(.status != "ready" and .status != "failed")] | length')" = 0 ]; do sleep 3; done
echo "processing: $(echo "$(date +%s.%N) - $T0" | bc) s"
curl -s $BASE/courses/$COURSE/documents -H "$AUTH" | jq '[.items[] | {id, status, page_count, chunk_count, error_code}]'
DOC=$(curl -s $BASE/courses/$COURSE/documents -H "$AUTH" | jq -r '.items[0].id')
```

Expected: every document `ready`. Record the processing time and the page counts.

## 3. Chat, summary, quiz

```bash
CONV=$(curl -s -X POST $BASE/courses/$COURSE/conversations -H "$AUTH" -H 'Content-Type: application/json' -d '{}' | jq -r .id)
curl -s -X POST $BASE/conversations/$CONV/messages -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"question":"<a question your lecture answers>"}' | jq '{state, refusal_reason, citations: [.citations[] | .citation_label]}'

curl -s -X POST $BASE/documents/$DOC/summary -H "$AUTH" -H 'Content-Type: application/json' -d '{}' | jq .status
until [ "$(curl -s $BASE/documents/$DOC/summary -H "$AUTH" | jq -r .status)" != generating ]; do sleep 2; done
curl -s $BASE/documents/$DOC/summary -H "$AUTH" | jq '{status, grounding, sections: (.sections | length)}'

T1=$(date +%s.%N)
QUIZ=$(curl -s -X POST $BASE/courses/$COURSE/quizzes -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"question_count":10,"question_types":["mcq","true_false"]}' | jq -r .id)
until [ "$(curl -s $BASE/quizzes/$QUIZ -H "$AUTH" | jq -r .status)" != generating ]; do sleep 2; done
echo "quiz generation: $(echo "$(date +%s.%N) - $T1" | bc) s"   # NFR-PER-05: under 45 s
curl -s $BASE/quizzes/$QUIZ -H "$AUTH" | jq '{status, question_count, notice}'
grep '"quiz job' ~/demo_run.log | jq -r .message                  # drops by reason (quiz yield)
```

Expected: chat `answered` (or `partial`) with citations; summary `ready`; quiz `ready` with 8-10 questions.

## 4. Take the quiz, submit, retry (NFR-PER-01 and NFR-PER-06)

```bash
ATTEMPT=$(curl -s -X POST $BASE/quizzes/$QUIZ/attempts -H "$AUTH" | tee /tmp/attempt.json | jq -r .id)
jq -r '.questions[] | "\(.position). [\(.type)] \(.stem)\n   \(.options // ["true", "false"] | to_entries | map("\(.key): \(.value)") | join("   "))"' /tmp/attempt.json
```

Answer each question (`choice` 0-3 for multiple choice, `value` true/false), timing one save:

```bash
Q=<question id>; curl -s -o /dev/null -w 'save: %{time_total} s\n' -X PUT $BASE/attempts/$ATTEMPT/answers/$Q \
  -H "$AUTH" -H 'Content-Type: application/json' -d '{"choice": 2}'
curl -s -o /dev/null -w 'save: %{time_total} s\n' -X PUT $BASE/attempts/$ATTEMPT/answers/<tf question id> \
  -H "$AUTH" -H 'Content-Type: application/json' -d '{"value": true}'
```

Submit and read the results:

```bash
curl -s -w '\nsubmit: %{time_total} s\n' -X POST $BASE/attempts/$ATTEMPT/submit -H "$AUTH" -o /tmp/results.json
jq '{score, max_score, percent, time_spent_seconds, topics}' /tmp/results.json
jq '.questions[] | select(.correct | not) | {position, answer, correct_answer, citation: .citation.citation_label, rationale}' /tmp/results.json
RETRY=$(curl -s -X POST $BASE/attempts/$ATTEMPT/retry-missed -H "$AUTH" | jq -r .id)
curl -s $BASE/attempts/$RETRY -H "$AUTH" | jq '{status, question_count}'
```

Expected: save under 0.3 s; submit under 1 s; every missed question has a correct answer, an evidence quote and a
citation to your own document; the retry holds exactly the missed questions. Answer and submit the retry the same way.

## 5. Tokens and the record

```bash
python - "$EMAIL" <<'EOF'
import sqlite3, sys
db = sqlite3.connect("data/backend/intellistudy.sqlite3")
uid = db.execute("SELECT id FROM users WHERE email = ?", (sys.argv[1],)).fetchone()[0]
for r in db.execute("""SELECT feature, COUNT(*), SUM(prompt_tokens + completion_tokens) FROM llm_usage
                       WHERE owner_id = ? GROUP BY feature""", (uid,)):
    print("%-8s calls=%d tokens=%d" % r)
EOF
```

Record in the M5 gate (section 2.10), without document content:

| Measure | Target | Result |
|---|---|---|
| Processing time, pages | NFR-PER-04: 50 text pages under 90 s | |
| Quiz generation time | NFR-PER-05: under 45 s | |
| Quiz yield (questions / requested; drops by reason) | 8 or more of 10 | |
| Answer save time | NFR-PER-01: under 300 ms | |
| Submit and results time | NFR-PER-06: under 1 s | |
| Tokens by feature (chat, summary, quiz) | within the 200,000 daily budget | |
| Cited explanations for every missed question | all | |
| Retry holds exactly the missed questions | yes | |

## 6. Clean up

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X DELETE $BASE/courses/$COURSE -H "$AUTH"   # 204: everything of the course is removed
```

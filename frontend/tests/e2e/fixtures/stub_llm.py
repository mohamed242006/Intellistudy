"""DETERMINISTIC TEST PROVIDER for the end-to-end suite (docs/F1_GATE.md section 4). Not a real model, never DeepSeek.

A tiny OpenAI-compatible ``POST /v1/chat/completions`` server on 127.0.0.1, used through the backend's existing
``local`` provider slot (INTELLISTUDY_LLM_PROVIDER=local, INTELLISTUDY_LLM_BASE_URL); no backend code changes. It
answers only from the sources in the prompt, so the backend's real citation parsing, grounding check, citation
ownership validation and state rules still decide every outcome:

* summary prompts: one "### [S#]" block per source with that source's first sentence, cited [S#];
* chat prompts: the first sentence of S1, cited [S1] (answered);
  a question containing "multiplied" (a word of the fixtures, so retrieval sees no missing term) adds a sentence
  citing a tag that was not provided (low confidence);
  a question containing "outage" gets HTTP 503 (the provider is unavailable).
Partial and refused states come from retrieval (missing terms, nothing relevant), not from this stub.

* quiz prompts (F2): one question per distinct source sentence, alternating multiple choice and true/false within the
  requested types. The correct option is the sentence's own keyword (a word no other sentence uses); distractors are
  other sentences' keywords; every other true/false statement swaps its keyword for another one, so it is false.
  Evidence is the sentence copied word for word. The backend's quiz validation (structure, quoted evidence, support,
  single answer, near-duplicates) still decides which questions are kept, and the backend shuffles the options.

Usage: python stub_llm.py PORT
"""

from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "deterministic-test-stub"
_SOURCE = re.compile(r'<source id="(S\d+)"[^>]*>\n(.*?)\n</source>', re.DOTALL)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def first_sentence(body: str) -> str:
    body = body.split("\n\n[Wider section]\n", 1)[0]
    for sentence in _SENTENCE.split(" ".join(body.split())):
        if len(sentence.split()) >= 4:
            return sentence.rstrip(".!?")
    return " ".join(body.split())[:200].rstrip(".!?")


_WORD = re.compile(r"[A-Za-z]{5,}")
_REQUEST = re.compile(r"Write (\d+) (.+?) questions as one JSON object")


def sentences_of(tag: str, body: str) -> list[tuple[str, str]]:
    text = " ".join(body.split("\n\n[Wider section]\n", 1)[0].split())
    seen: list[tuple[str, str]] = []
    for raw in _SENTENCE.split(text):
        sentence = raw.strip()
        if len(sentence.split()) >= 6 and sentence.endswith(".") and sentence not in {s for _, s in seen}:
            seen.append((tag, sentence))
    return seen


def quiz_reply(user: str, sources: list[tuple[str, str]]) -> str:
    match = _REQUEST.search(user)
    count = int(match.group(1)) if match else 5
    kinds = match.group(2) if match else "multiple-choice and true/false"
    types = [t for t, word in (("mcq", "multiple-choice"), ("true_false", "true/false")) if word in kinds]
    pool = [item for tag, body in sources for item in sentences_of(tag, body)]
    words = [{w.lower() for w in _WORD.findall(s)} for _, s in pool]
    keywords: list[str | None] = []
    for i, (_, sentence) in enumerate(pool):
        others = set().union(*(w for j, w in enumerate(words) if j != i)) if len(words) > 1 else set()
        unique = sorted((w for w in _WORD.findall(sentence) if w.lower() not in others), key=lambda w: (-len(w), w))
        keywords.append(unique[0] if unique else None)
    usable = [(tag, s, k) for (tag, s), k in zip(pool, keywords, strict=True) if k]
    questions = []
    for i, (tag, sentence, keyword) in enumerate(usable[:count]):
        others = [k for _, _, k in usable if k != keyword]
        kind = types[i % len(types)]
        common = {"sources": [tag], "evidence": sentence, "difficulty": "easy", "cognitive_level": "remember",
                  "topic": "Queueing basics" if i < len(usable) // 2 else "Queue behaviour"}
        if kind == "mcq" and len(others) >= 3:
            distractors = others[i % len(others):] + others[: i % len(others)]
            options = [keyword, *distractors[:3]]
            questions.append({"type": "mcq", "stem": f"Which word completes this statement from your notes: "
                              f"\"{sentence.replace(keyword, '_____')}\"", "options": options, "correct_index": 0,
                              "rationales": [f"The cited sentence uses \"{keyword}\"."] +
                              [f"\"{d}\" belongs to a different statement." for d in distractors[:3]], **common})
        else:
            false = i % 4 == 3 and others
            stem = sentence.replace(keyword, others[0]) if false else sentence
            questions.append({"type": "true_false", "stem": stem, "answer": not false,
                              "rationale": f"The cited sentence uses \"{keyword}\"." if false else
                              "The cited sentence says exactly this.", **common})
    return json.dumps({"questions": questions})


def reply_for(messages: list[dict[str, str]]) -> tuple[int, str]:
    system = messages[0]["content"] if messages else ""
    user = messages[-1]["content"] if messages else ""
    sources = _SOURCE.findall(user)
    if not sources:
        return 200, "INSUFFICIENT_CONTEXT"
    if "practice questions" in system:
        return 200, quiz_reply(user, sources)
    if "study summary" in system:
        return 200, "\n\n".join(f"### [{tag}]\n{first_sentence(body)} [{tag}]." for tag, body in sources)
    question = user.rsplit("Question:", 1)[-1].strip().lower()
    if "outage" in question:
        return 503, ""
    tag, body = sources[0]
    text = f"{first_sentence(body)} [{tag}]."
    if "multiplied" in question:
        text += f" {first_sentence(body)} [S99]."
    return 200, text


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # http.server API name
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        status, text = reply_for(payload.get("messages") or [])
        if status != 200:
            self.send_response(status)
            self.end_headers()
            return
        body = json.dumps({
            "model": MODEL,
            "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": len(json.dumps(payload)) // 4, "completion_tokens": len(text) // 4},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # quiet: prompts contain document text
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()

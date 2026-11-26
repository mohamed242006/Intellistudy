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


def reply_for(messages: list[dict[str, str]]) -> tuple[int, str]:
    system = messages[0]["content"] if messages else ""
    user = messages[-1]["content"] if messages else ""
    sources = _SOURCE.findall(user)
    if not sources:
        return 200, "INSUFFICIENT_CONTEXT"
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

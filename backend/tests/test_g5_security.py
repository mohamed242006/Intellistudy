"""M5 gate 2.8: security release verification (contract 10.7) over the whole API.

The route map below is explicit: every operation of the OpenAPI document must be listed, so a route added later fails
these tests until its expected behaviour is declared here (G5-SEC-02..04).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from backend.app.db.models import Course, Document, Quiz
from backend.tests.m5_base import M5Case

ROOT = Path(__file__).resolve().parents[2]
RANDOM = "00000000-0000-4000-8000-000000000000"
MALFORMED = "not-a-uuid"
KEY_FIELD = re.compile(r"^(correct.*|answer_key|rationale.*|evidence|is_correct)$")

#: every operation of the API -> the JSON body sent in these tests (None: no body)
ROUTES: dict[tuple[str, str], Any] = {
    ("GET", "/api/v1/health"): None,
    ("POST", "/api/v1/auth/register"): {"email": "x@example.org", "name": "X", "password": "lectures4ever"},
    ("POST", "/api/v1/auth/login"): {"email": "x@example.org", "password": "lectures4ever"},
    ("POST", "/api/v1/auth/refresh"): None,
    ("POST", "/api/v1/auth/logout"): None,
    ("POST", "/api/v1/auth/logout-all"): None,
    ("GET", "/api/v1/auth/me"): None,
    ("POST", "/api/v1/auth/change-password"): {"current_password": "lectures4ever", "new_password": "betterlectures5"},
    ("POST", "/api/v1/courses"): {"name": "New"},
    ("GET", "/api/v1/courses"): None,
    ("GET", "/api/v1/courses/{course_id}"): None,
    ("PATCH", "/api/v1/courses/{course_id}"): {"name": "Renamed"},
    ("DELETE", "/api/v1/courses/{course_id}"): None,
    ("POST", "/api/v1/courses/{course_id}/documents"): None,
    ("GET", "/api/v1/courses/{course_id}/documents"): None,
    ("GET", "/api/v1/documents/{document_id}"): None,
    ("DELETE", "/api/v1/documents/{document_id}"): None,
    ("GET", "/api/v1/documents/{document_id}/file"): None,
    ("POST", "/api/v1/documents/{document_id}/retry"): None,
    ("POST", "/api/v1/courses/{course_id}/conversations"): {},
    ("GET", "/api/v1/courses/{course_id}/conversations"): None,
    ("GET", "/api/v1/conversations/{conversation_id}"): None,
    ("DELETE", "/api/v1/conversations/{conversation_id}"): None,
    ("POST", "/api/v1/conversations/{conversation_id}/messages"): {"question": "What do mitochondria produce?"},
    ("GET", "/api/v1/documents/{document_id}/summary"): None,
    ("POST", "/api/v1/documents/{document_id}/summary"): {},
    ("POST", "/api/v1/courses/{course_id}/quizzes"): {"question_count": 5},
    ("GET", "/api/v1/courses/{course_id}/quizzes"): None,
    ("GET", "/api/v1/quizzes/{quiz_id}"): None,
    ("DELETE", "/api/v1/quizzes/{quiz_id}"): None,
    ("POST", "/api/v1/quizzes/{quiz_id}/regenerate"): None,
    ("POST", "/api/v1/quizzes/{quiz_id}/attempts"): None,
    ("GET", "/api/v1/quizzes/{quiz_id}/attempts"): None,
    ("GET", "/api/v1/attempts/{attempt_id}"): None,
    ("PUT", "/api/v1/attempts/{attempt_id}/answers/{question_id}"): {"choice": 0},
    ("POST", "/api/v1/attempts/{attempt_id}/submit"): None,
    ("GET", "/api/v1/attempts/{attempt_id}/results"): None,
    ("POST", "/api/v1/attempts/{attempt_id}/retry-missed"): None,
}
PUBLIC = {("GET", "/api/v1/health"), ("POST", "/api/v1/auth/register"), ("POST", "/api/v1/auth/login"),
          ("POST", "/api/v1/auth/refresh"), ("POST", "/api/v1/auth/logout")}
#: routes whose attempt must be a submitted one for the call to make sense
SUBMITTED_ATTEMPT = {"/api/v1/attempts/{attempt_id}/results", "/api/v1/attempts/{attempt_id}/retry-missed"}
SECURITY_HEADERS = {"x-content-type-options": "nosniff", "referrer-policy": "no-referrer", "x-frame-options": "DENY",
                    "cache-control": "no-store"}


def fill(path: str, ids: dict[str, str]) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: ids[m.group(1)], path)


class SecurityCase(M5Case):
    def setUp(self) -> None:
        super().setUp()
        self.quiz = self.ready_quiz([self.doc_cells, self.doc_nerves])
        self.submitted, _ = self.take(self.quiz["id"], wrong={1})
        self.current = self.start_ok(self.quiz["id"])
        self.summary_ok(self.a, self.a_token, self.doc_cells)
        conversation = self.a.post(f"/api/v1/courses/{self.a_course}/conversations", json={},
                                   headers=self.bearer(self.a_token))
        self.assertEqual(conversation.status_code, 201, conversation.text)
        self.ids = {"course_id": self.a_course, "document_id": self.doc_cells,
                    "conversation_id": conversation.json()["id"], "quiz_id": self.quiz["id"],
                    "attempt_id": self.current["id"], "question_id": self.current["questions"][0]["id"]}

    def operations(self) -> set[tuple[str, str]]:
        spec = self.app.openapi()
        return {(method.upper(), path) for path, ops in spec["paths"].items() for method in ops}

    def call(self, client: Any, method: str, path: str, ids: dict[str, str], headers: dict[str, str],
             body: Any = ...) -> Any:
        url = fill(path, ids)
        payload = ROUTES[(method, path)] if body is ... else body
        if payload is None:
            return client.request(method, url, headers=headers)
        return client.request(method, url, json=payload, headers=headers)

    def a_ids(self, path: str) -> dict[str, str]:
        return {**self.ids, "attempt_id": self.submitted["id"]} if path in SUBMITTED_ATTEMPT else self.ids


class SecurityVerificationTests(SecurityCase):
    def test_g5_sec_01_every_contract_row_is_mapped_to_existing_tests(self) -> None:
        contract = (ROOT / "docs" / "backend_security_contract.md").read_text(encoding="utf-8")
        matrix = contract[contract.index("### 10.1"):contract.index("### 10.7")]
        rows = re.findall(r"^\| ([IRAUPS]-\d+) \|", matrix, re.M)
        record = (ROOT / "docs" / "SECURITY_VERIFICATION.md").read_text(encoding="utf-8")
        section = record[record.index("## 1."):record.index("## 2.")]
        mapped = {m.group(1): m.group(2) for m in re.finditer(r"^\| ([IRAUPS]-\d+) \|[^|]*\| (.+) \|$", section, re.M)}
        self.assertEqual(len(rows), 70)
        self.assertEqual(sorted(mapped), sorted(rows))
        gate_tests: set[str] = set()
        for path in (ROOT / "backend" / "tests").glob("test_g*.py"):
            gate_tests |= set(re.findall(r"^    def test_(g\d_[a-z0-9]+_\d+)_", path.read_text(encoding="utf-8"), re.M))
        for row, cell in mapped.items():
            refs = re.findall(r"`([^`]+)`", cell)
            with self.subTest(row=row):
                self.assertTrue(refs)
                for ref in refs:
                    if "::" in ref:
                        file, function = ref.split("::")
                        source = ROOT / file
                        self.assertTrue(source.name.startswith("test_") and source.is_file(), ref)
                        self.assertRegex(source.read_text(encoding="utf-8"), rf"(?m)^    def {re.escape(function)}\(")
                    else:
                        self.assertIn(ref.lower().replace("-", "_"), gate_tests, ref)

    def test_g5_sec_02_every_route_requires_a_token_except_the_allowlist(self) -> None:
        operations = self.operations()
        self.assertEqual(operations, set(ROUTES), "a route was added or removed: declare it in ROUTES")
        ids = dict.fromkeys(self.ids, RANDOM)
        for method, path in sorted(operations - PUBLIC):
            with self.subTest(route=f"{method} {path}"):
                self.assert_generic_401(self.call(self.client(), method, path, ids, {}))

    def test_g5_sec_03_random_and_malformed_ids_on_every_id_route(self) -> None:
        id_routes = sorted(op for op in self.operations() if "{" in op[1])
        self.assertEqual(set(id_routes), {op for op in ROUTES if "{" in op[1]})
        for bad in (RANDOM, MALFORMED):
            for method, path in id_routes:
                with self.subTest(bad=bad, route=f"{method} {path}"):
                    response = self.call(self.a, method, path, dict.fromkeys(self.ids, bad), self.bearer(self.a_token))
                    self.assert_same_404(response, self.a_token)

    def test_g5_sec_04_another_student_gets_the_same_404_on_every_id_route(self) -> None:
        id_routes = sorted(op for op in self.operations() if "{" in op[1])
        before = (self.stored_state(self.submitted["id"]), self.stored_state(self.current["id"]))
        for method, path in id_routes:
            with self.subTest(route=f"{method} {path}"), self.assertLogs("intellistudy.security", level="WARNING"):
                response = self.call(self.b, method, path, self.a_ids(path), self.bearer(self.b_token))
                self.assert_same_404(response, self.b_token)
        self.assertEqual((self.stored_state(self.submitted["id"]), self.stored_state(self.current["id"])), before)
        self.assertEqual(self.count(Course, Course.id == self.a_course), 1)
        self.assertEqual(self.count(Document, Document.course_id == self.a_course, Document.status == "ready"), 2)
        self.assertEqual(self.count(Quiz, Quiz.id == self.quiz["id"], Quiz.status == "ready"), 1)

    def test_g5_sec_05_headers_and_problem_bodies_on_every_route(self) -> None:
        responses: list[Any] = []
        for method, path in sorted(ROUTES):
            if method == "GET":
                responses.append(self.call(self.a, method, path, self.a_ids(path), self.bearer(self.a_token)))
            if "{" in path:
                responses.append(self.call(self.a, method, path, dict.fromkeys(self.ids, RANDOM),
                                           self.bearer(self.a_token)))
            elif (method, path) not in PUBLIC:
                responses.append(self.call(self.client(), method, path, {}, {}))
        responses.append(self.results(self.current["id"]))  # 409
        responses.append(self.put_answer(self.current["id"], self.ids["question_id"], choice=9))  # 422
        self.assertTrue(any(r.status_code == 200 for r in responses))
        for response in responses:
            with self.subTest(url=str(response.url), status=response.status_code):
                for name, value in SECURITY_HEADERS.items():
                    self.assertEqual(response.headers.get(name), value)
                self.assertIn("frame-ancestors 'none'", response.headers.get("content-security-policy", ""))
                if response.status_code >= 400:
                    self.assertEqual(response.headers["content-type"], "application/problem+json")
                    body = response.json()
                    self.assertLessEqual({"type", "title", "status"}, set(body))
                    self.assertNotIn("Traceback", response.text)
                    self.assertNotIn('File "', response.text)

    def test_g5_sec_06_every_request_body_rejects_unknown_fields(self) -> None:
        spec = self.app.openapi()
        bodies = []
        for path, ops in spec["paths"].items():
            for method, op in ops.items():
                schema = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
                if schema is None:
                    continue
                name = schema["$ref"].rsplit("/", 1)[-1]
                with self.subTest(model=name):
                    self.assertIs(spec["components"]["schemas"][name].get("additionalProperties"), False)
                bodies.append((method.upper(), path))
        self.assertEqual(len(bodies), 10)
        for method, path in bodies:
            body = {**ROUTES[(method, path)], "unexpected_field": 1}
            with self.subTest(route=f"{method} {path}"):
                response = self.call(self.a, method, path, self.a_ids(path), self.bearer(self.a_token), body)
                self.assertEqual(response.status_code, 422, response.text)

    def test_g5_sec_07_answer_key_fields_only_in_the_results_schema(self) -> None:
        schemas = self.app.openapi()["components"]["schemas"]
        with_keys = {name for name, schema in schemas.items()
                     if any(KEY_FIELD.match(f) for f in schema.get("properties", {}))}
        self.assertEqual(with_keys, {"ResultQuestion"})
        results = schemas["AttemptResults"]["properties"]["questions"]["items"]["$ref"]
        self.assertTrue(results.endswith("/ResultQuestion"))
        self.assertTrue(all(isinstance(s, dict) for s in schemas.values()))

    def test_g5_sec_08_owasp_checklist_has_no_open_item(self) -> None:
        record = (ROOT / "docs" / "SECURITY_VERIFICATION.md").read_text(encoding="utf-8")
        contract = (ROOT / "docs" / "backend_security_contract.md").read_text(encoding="utf-8")
        findings = set(re.findall(r"^\| (F-M\d-\d+) \|", contract, re.M))
        items = re.findall(r"^\| ((?:A|LLM)\d{2}) [^|]+\| ([^|]+) \| ([^|]+) \|$", record, re.M)
        self.assertEqual(sorted(i[0] for i in items),
                         sorted([f"A{n:02d}" for n in range(1, 11)] + [f"LLM{n:02d}" for n in range(1, 11)]))
        for item, status, evidence in items:
            status = status.strip()
            with self.subTest(item=item):
                self.assertIn(status, {"pass", "residual", "n/a"})
                if status == "residual":
                    cited = set(re.findall(r"F-M\d-\d+", evidence))
                    self.assertTrue(cited)
                    self.assertLessEqual(cited, findings)
                elif status == "pass":
                    self.assertRegex(evidence, r"\b[A-Z]{2,4}-\d{2}\b|\bG\d-[A-Z]+")
                else:
                    self.assertGreater(len(evidence.strip()), 20)

"""M1 gate sections 3-5: cross-user isolation (G1-ISO), IDOR (G1-IDOR), ownership enforcement (G1-OWN)."""

from __future__ import annotations

import ast
import statistics
import time
import uuid
from pathlib import Path

from sqlalchemy import func, inspect, select

from backend.app.core.errors import ApiError
from backend.app.db.models import Course, RefreshToken, User
from backend.app.services.ownership import get_owned
from backend.tests.m1_base import CSRF, M1Case

ROOT = Path(__file__).resolve().parents[2]
COURSE_ROUTES = ("GET", "PATCH", "DELETE")


class CrossUserIsolationTests(M1Case):
    def course_url(self, course_id: str) -> str:
        return f"/api/v1/courses/{course_id}"

    def a_course_state(self) -> tuple:
        with self.db() as session:
            c = session.scalars(select(Course).where(Course.id == self.a_course)).one()
            return c.name, c.code, c.archived, c.updated_at

    def test_g1_iso_01_read_of_another_users_course(self) -> None:
        before = self.a_course_state()
        with self.assertLogs("intellistudy.security", level="WARNING") as logs:
            response = self.b.get(self.course_url(self.a_course), headers=self.bearer(self.b_token))
        self.assert_same_404(response, self.b_token)
        self.assertEqual(self.a_course_state(), before)
        events = [getattr(r, "security_event", {}) for r in logs.records
                  if getattr(r, "security_event", {}).get("event") == "ownership_mismatch"]
        self.assertEqual(events, [{"event": "ownership_mismatch", "user_id": self.b_id, "resource": "course",
                                   "resource_id": self.a_course}])

    def test_g1_iso_02_update_of_another_users_course(self) -> None:
        before = self.a_course_state()
        self.clock.advance(60)
        with self.assertLogs("intellistudy.security", level="WARNING") as logs:
            response = self.b.patch(self.course_url(self.a_course), json={"name": "hijacked", "archived": True},
                                    headers=self.bearer(self.b_token))
        self.assert_same_404(response, self.b_token)
        self.assertEqual(self.a_course_state(), before)
        self.assertTrue(any(getattr(r, "security_event", {}).get("event") == "ownership_mismatch" for r in logs.records))

    def test_g1_iso_03_delete_of_another_users_course(self) -> None:
        with self.assertLogs("intellistudy.security", level="WARNING"):
            response = self.b.delete(self.course_url(self.a_course), headers=self.bearer(self.b_token))
        self.assert_same_404(response, self.b_token)
        self.assertEqual(self.a.get(self.course_url(self.a_course), headers=self.bearer(self.a_token)).status_code, 200)

    def test_g1_iso_04_list_shows_only_own_courses(self) -> None:
        for i in range(3):
            self.create_course(self.a_token, f"A extra {i}")
        body = self.b.get("/api/v1/courses?include_archived=true&limit=100", headers=self.bearer(self.b_token)).json()
        self.assertEqual([c["id"] for c in body["items"]], [self.b_course])
        self.assertEqual(set(body), {"items", "limit", "offset"})  # no total or count of anyone else's
        self.assertNotIn(self.a_course, str(body))

    def test_g1_iso_05_same_name_and_code_are_independent(self) -> None:
        a2 = self.create_course(self.a_token, "Same Name", "SAME1")
        b2 = self.create_course(self.b_token, "Same Name", "SAME1")
        self.assertNotEqual(a2, b2)
        a_ids = {c["id"] for c in self.a.get("/api/v1/courses", headers=self.bearer(self.a_token)).json()["items"]}
        b_ids = {c["id"] for c in self.b.get("/api/v1/courses", headers=self.bearer(self.b_token)).json()["items"]}
        self.assertIn(a2, a_ids)
        self.assertNotIn(b2, a_ids)
        self.assertIn(b2, b_ids)
        self.assertNotIn(a2, b_ids)

    def test_g1_iso_06_every_course_route_returns_404_never_403(self) -> None:
        for method in COURSE_ROUTES:
            with self.subTest(method=method), self.assertLogs("intellistudy.security", level="WARNING"):
                kwargs = {"json": {"name": "x"}} if method == "PATCH" else {}
                response = self.b.request(method, self.course_url(self.a_course), headers=self.bearer(self.b_token),
                                          **kwargs)
                self.assert_same_404(response, self.b_token)
                self.assertNotEqual(response.status_code, 403)

    def test_g1_iso_07_me_returns_only_the_callers_profile(self) -> None:
        body = self.b.get("/api/v1/auth/me", headers=self.bearer(self.b_token)).json()
        self.assertEqual(body["id"], self.b_id)
        self.assertEqual(set(body), {"id", "email", "name", "role", "created_at"})
        text = str(body)
        for leak in ("a@example.org", self.a_id, "argon2", "failed_logins", "locked_until", "token"):
            self.assertNotIn(leak, text)

    def test_g1_iso_08_refresh_cookie_owner_decides_the_session(self) -> None:
        response = self.a.post("/api/v1/auth/refresh", headers={**CSRF, **self.bearer(self.b_token)})
        self.assertEqual(response.status_code, 200)
        me = self.client().get("/api/v1/auth/me", headers=self.bearer(response.json()["access_token"])).json()
        self.assertEqual(me["id"], self.a_id)
        self.assertEqual(self.b.get("/api/v1/auth/me", headers=self.bearer(self.b_token)).json()["id"], self.b_id)

    def test_g1_iso_09_admin_role_grants_no_access_to_other_users_courses(self) -> None:
        for method in COURSE_ROUTES:
            with self.subTest(method=method), self.assertLogs("intellistudy.security", level="WARNING"):
                kwargs = {"json": {"name": "admin edit"}} if method == "PATCH" else {}
                response = self.c.request(method, self.course_url(self.a_course), headers=self.bearer(self.c_token),
                                          **kwargs)
                self.assert_same_404(response, self.c_token)
        listed = self.c.get("/api/v1/courses", headers=self.bearer(self.c_token)).json()["items"]
        self.assertEqual(listed, [])


class IdorTests(M1Case):
    def test_g1_idor_01_ids_are_server_generated_uuid4(self) -> None:
        ids = {self.create_course(self.a_token, f"c{i}") for i in range(30)}
        with self.db() as session:
            ids |= set(session.scalars(select(User.id))) | set(session.scalars(select(RefreshToken.id)))
            ids |= set(session.scalars(select(RefreshToken.family_id)))
        self.assertTrue(all(uuid.UUID(i).version == 4 and str(uuid.UUID(i)) == i for i in ids))
        many = {self.create_course(self.b_token, f"m{i}") for i in range(1000)}
        self.assertEqual(len(many), 1000)

    def test_g1_idor_02_client_chosen_id_is_rejected(self) -> None:
        chosen = str(uuid.uuid4())
        response = self.a.post("/api/v1/courses", json={"name": "x", "id": chosen}, headers=self.bearer(self.a_token))
        self.assertEqual(response.status_code, 422)
        with self.db() as session:
            self.assertIsNone(session.scalar(select(Course.id).where(Course.id == chosen)))

    def test_g1_idor_03_random_uuid_is_404_without_ownership_event(self) -> None:
        random_id = str(uuid.uuid4())
        for method in COURSE_ROUTES:
            with self.subTest(method=method):
                kwargs = {"json": {"name": "x"}} if method == "PATCH" else {}
                with self.assertNoLogs("intellistudy.security", level="WARNING"):
                    response = self.b.request(method, f"/api/v1/courses/{random_id}", headers=self.bearer(self.b_token),
                                              **kwargs)
                self.assert_same_404(response, self.b_token)

    def test_g1_idor_04_malformed_ids_are_the_same_404(self) -> None:
        bad_ids = ["123", "abc", "%00", "x" * 1000, self.a_course.upper(), self.a_course + " ", "../" + self.a_course]
        for raw in bad_ids:
            for method in COURSE_ROUTES:
                with self.subTest(id=raw[:20], method=method):
                    kwargs = {"json": {"name": "x"}} if method == "PATCH" else {}
                    response = self.a.request(method, f"/api/v1/courses/{raw}", headers=self.bearer(self.a_token),
                                              **kwargs)
                    self.assert_same_404(response, self.a_token)
                    self.assertNotIn("Traceback", response.text)

    def test_g1_idor_05_no_existence_timing_oracle(self) -> None:
        def mean_ms(course_id: str) -> float:
            samples = []
            for _ in range(200):
                started = time.perf_counter()
                response = self.b.get(f"/api/v1/courses/{course_id}", headers=self.bearer(self.b_token))
                samples.append((time.perf_counter() - started) * 1000)
                self.assertEqual(response.status_code, 404)
            return statistics.mean(samples)

        import logging
        logging.disable(logging.WARNING)  # keep 200 security events out of the timing
        try:
            foreign = mean_ms(self.a_course)
            random_ = mean_ms(str(uuid.uuid4()))
        finally:
            logging.disable(logging.NOTSET)
        self.assertLess(abs(foreign - random_), 20.0, (foreign, random_))

    def test_g1_idor_06_no_sequential_identifiers_in_responses(self) -> None:
        bodies = [
            self.a.get("/api/v1/auth/me", headers=self.bearer(self.a_token)).json(),
            self.a.get(f"/api/v1/courses/{self.a_course}", headers=self.bearer(self.a_token)).json(),
            *self.a.get("/api/v1/courses", headers=self.bearer(self.a_token)).json()["items"],
        ]
        for body in bodies:
            uuid.UUID(body["id"])  # every id is a UUID
            for key, value in body.items():
                if key.endswith("id"):
                    self.assertEqual(uuid.UUID(value).version, 4, key)
                if not isinstance(value, bool):  # bool is a subclass of int; flags are fine
                    self.assertNotIsInstance(value, int, key)  # no row numbers / counters


class OwnershipEnforcementTests(M1Case):
    def test_g1_own_01_ownership_fields_in_body_are_rejected(self) -> None:
        for field in ("owner_id", "user_id", "course_id"):
            with self.subTest(field=field):
                response = self.a.post("/api/v1/courses", json={"name": "x", field: self.b_id},
                                       headers=self.bearer(self.a_token))
                self.assertEqual(response.status_code, 422)
                self.assertIn("extra_forbidden", {e["type"] for e in response.json()["errors"]})
                self.assertNotIn(self.b_id, response.text)

    def test_g1_own_02_owner_comes_from_the_token(self) -> None:
        course_id = self.create_course(self.a_token, "mine")
        with self.db() as session:
            self.assertEqual(session.scalar(select(Course.owner_id).where(Course.id == course_id)), self.a_id)

    def test_g1_own_03_owner_cannot_be_changed_by_update(self) -> None:
        response = self.a.patch(f"/api/v1/courses/{self.a_course}", json={"owner_id": self.b_id},
                                headers=self.bearer(self.a_token))
        self.assertEqual(response.status_code, 422)
        with self.db() as session:
            self.assertEqual(session.scalar(select(Course.owner_id).where(Course.id == self.a_course)), self.a_id)

    def test_g1_own_04_no_unscoped_lookups_in_api_or_services(self) -> None:
        offenders = []
        for base in ("api", "services"):
            for path in sorted((ROOT / "backend" / "app" / base).rglob("*.py")):
                if path.name == "ownership.py":
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        if node.func.attr == "get" and isinstance(node.func.value, ast.Name) and \
                                node.func.value.id in {"session", "db"}:
                            offenders.append(f"{path.name}:{node.lineno} session.get")
                        if node.func.attr in {"text", "exec_driver_sql"}:
                            offenders.append(f"{path.name}:{node.lineno} raw SQL")
                for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
                    source = ast.unparse(fn)
                    if "select(Course)" in source and "owner_id" not in source and "get_owned" not in source:
                        offenders.append(f"{path.name}:{fn.name} select(Course) without owner filter")
        allowed_raw_sql = {"health.py"}  # SELECT 1 liveness probe
        offenders = [o for o in offenders if not (o.endswith("raw SQL") and o.split(":")[0] in allowed_raw_sql)]
        self.assertEqual(offenders, [])

    def test_g1_own_05_get_owned_semantics(self) -> None:
        with self.db() as session:
            self.assertEqual(get_owned(session, Course, self.a_course, self.a_id, resource="course").id, self.a_course)
            for raw, owner, expect_event in ((self.a_course, self.b_id, True), (str(uuid.uuid4()), self.a_id, False),
                                              ("not-a-uuid", self.a_id, False)):
                with self.subTest(raw=raw[:12]):
                    if expect_event:
                        with self.assertLogs("intellistudy.security", level="WARNING"), self.assertRaises(ApiError) as ctx:
                            get_owned(session, Course, raw, owner, resource="course")
                    else:
                        with self.assertNoLogs("intellistudy.security", level="WARNING"), \
                                self.assertRaises(ApiError) as ctx:
                            get_owned(session, Course, raw, owner, resource="course")
                    self.assertEqual((ctx.exception.status, ctx.exception.code, ctx.exception.detail),
                                     (404, "not_found", "Resource not found."))

    def test_g1_own_06_owner_id_is_a_non_nullable_foreign_key(self) -> None:
        engine = self.app.state.engine
        inspector = inspect(engine)
        column = {c["name"]: c for c in inspector.get_columns("courses")}["owner_id"]
        self.assertFalse(column["nullable"])
        fks = inspector.get_foreign_keys("courses")
        self.assertIn(("owner_id", "users", "id"),
                      {(fk["constrained_columns"][0], fk["referred_table"], fk["referred_columns"][0]) for fk in fks})

    def test_g1_own_07_every_request_model_forbids_unknown_fields(self) -> None:
        # Read from the published OpenAPI schema (independent of FastAPI's internal route classes):
        # extra="forbid" renders as "additionalProperties": false on every request-body schema.
        spec = self.app.openapi()
        schemas = spec["components"]["schemas"]
        checked = []
        for path, operations in spec["paths"].items():
            for method, operation in operations.items():
                content = operation.get("requestBody", {}).get("content", {})
                for media in content.values():
                    ref = media["schema"].get("$ref", "")
                    name = ref.rsplit("/", 1)[-1]
                    self.assertTrue(name, f"{method} {path}: inline body schema")
                    self.assertIs(schemas[name].get("additionalProperties"), False, f"{method} {path}: {name}")
                    checked.append(f"{method} {path}")
        for expected in ("post /api/v1/auth/register", "post /api/v1/auth/login", "post /api/v1/auth/change-password",
                         "post /api/v1/courses", "patch /api/v1/courses/{course_id}"):
            self.assertIn(expected, checked)

    def test_g1_own_08_delete_removes_only_the_course(self) -> None:
        with self.db() as session:
            before = {m.__name__: int(session.scalar(select(func.count()).select_from(m)) or 0) for m in (User, Course, RefreshToken)}
        response = self.a.delete(f"/api/v1/courses/{self.a_course}", headers=self.bearer(self.a_token))
        self.assertEqual(response.status_code, 204)
        again = self.a.delete(f"/api/v1/courses/{self.a_course}", headers=self.bearer(self.a_token))
        self.assert_same_404(again, self.a_token)
        with self.db() as session:
            after = {m.__name__: int(session.scalar(select(func.count()).select_from(m)) or 0) for m in (User, Course, RefreshToken)}
            self.assertIsNotNone(session.scalar(select(Course.id).where(Course.id == self.b_course)))
        self.assertEqual(after, {**before, "Course": before["Course"] - 1})


if __name__ == "__main__":
    import unittest

    unittest.main()

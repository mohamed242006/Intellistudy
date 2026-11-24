"""M1 gate section 9: M0 properties re-checked against the M1 endpoints (G1-M0-01..07).

G1-M0-01/02 are enforced by CI jobs (gitleaks, pip-audit); these tests pin the workflow so the jobs cannot silently
disappear, and keep the pip-audit ignore list identical to the recorded exceptions in the contract (Appendix C).
"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest import mock

from backend.app.core.config import ConfigurationError, Settings
from backend.tests import test_static_rules
from backend.tests.m1_base import CSRF, M1Case

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "backend.yml"
CONTRACT = ROOT / "docs" / "backend_security_contract.md"


class CiGateTests(unittest.TestCase):
    def test_g1_m0_01_secret_scan_job_covers_full_history(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("gitleaks/gitleaks-action", text)
        self.assertIn("fetch-depth: 0", text)

    def test_g1_m0_02_pip_audit_ignores_exactly_the_recorded_exceptions(self) -> None:
        ignored = set(re.findall(r"--ignore-vuln\s+(\S+)", WORKFLOW.read_text(encoding="utf-8")))
        appendix = CONTRACT.read_text(encoding="utf-8").split("## Appendix C", 1)[1]
        recorded = set(re.findall(r"\b(PYSEC-\d{4}-\d+|GHSA-[\w-]+|CVE-\d{4}-\d+)\b", appendix.split("Resolved by", 1)[0]))
        self.assertTrue(ignored)
        self.assertEqual(ignored, recorded)

    def test_g1_m0_03_startup_refuses_weak_or_missing_secrets(self) -> None:
        clean = {k: v for k, v in os.environ.items() if not k.startswith("INTELLISTUDY_")}
        with mock.patch.dict(os.environ, clean, clear=True):
            for profile in ("demo", "prod"):
                for secret in (None, "short", "change-me"):
                    with self.subTest(profile=profile, secret=secret), self.assertRaises(ConfigurationError):
                        Settings(_env_file=None, profile=profile, llm_provider="none", jwt_secret=secret)

    def test_every_gate_item_has_exactly_one_test(self) -> None:
        """Gate rule 1: one ``test_g1_<id>_...`` per row of docs/SECURITY_MERGE_GATE.md, and no orphan tests."""
        gate = (ROOT / "docs" / "SECURITY_MERGE_GATE.md").read_text(encoding="utf-8")
        ids = {i.lower().replace("-", "_") for i in re.findall(r"^\| (G1-[A-Z0-9]+-\d+) \|", gate, re.M)}
        names: list[str] = []
        for path in (ROOT / "backend" / "tests").glob("test_g1_*.py"):
            names += re.findall(r"def test_(g1_[a-z0-9]+_\d+)_", path.read_text(encoding="utf-8"))
        self.assertEqual(len(ids), 79)
        self.assertEqual(sorted(set(names)), sorted(names), "duplicate gate tests")
        self.assertEqual(set(names), ids)

    def test_every_m2_gate_item_has_exactly_one_test(self) -> None:
        """Same rule for the M2 section: one ``test_g2_<id>_...`` per G2 row, no orphan tests."""
        gate = (ROOT / "docs" / "SECURITY_MERGE_GATE.md").read_text(encoding="utf-8")
        ids = {i.lower().replace("-", "_") for i in re.findall(r"^\| (G2-[A-Z0-9]+-\d+) \|", gate, re.M)}
        names: list[str] = []
        for path in (ROOT / "backend" / "tests").glob("test_g2_*.py"):
            names += re.findall(r"def test_(g2_[a-z0-9]+_\d+)_", path.read_text(encoding="utf-8"))
        self.assertTrue(ids)
        self.assertEqual(sorted(set(names)), sorted(names), "duplicate gate tests")
        self.assertEqual(set(names), ids)

    def test_every_m3_gate_item_has_exactly_one_test(self) -> None:
        """M3 release gate rule: one ``test_g3_<id>_...`` per row of docs/M3_RELEASE_GATE.md (52), no orphan tests."""
        gate = (ROOT / "docs" / "M3_RELEASE_GATE.md").read_text(encoding="utf-8")
        ids = {i.lower().replace("-", "_") for i in re.findall(r"^\| (G3-[A-Z0-9]+-\d+) \|", gate, re.M)}
        names: list[str] = []
        for path in (ROOT / "backend" / "tests").glob("test_g3_*.py"):
            names += re.findall(r"def test_(g3_[a-z0-9]+_\d+)_", path.read_text(encoding="utf-8"))
        self.assertEqual(len(ids), 52)
        self.assertEqual(sorted(set(names)), sorted(names), "duplicate gate tests")
        self.assertEqual(set(names), ids)

    def test_g1_m0_07_static_rules_still_pass(self) -> None:
        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(test_static_rules.StaticRuleTests).run(result)
        self.assertTrue(result.wasSuccessful(), result.failures + result.errors)
        self.assertEqual(result.skipped, [])


class HttpGateTests(M1Case):
    def m1_responses(self) -> dict[str, object]:
        """One response per M1 endpoint family, including error paths."""
        h = self.bearer(self.a_token)
        client = self.client("10.40.0.1")
        return {
            "register-422": client.post("/api/v1/auth/register", json={"email": "x", "name": "x", "password": "y"}),
            "login-401": client.post("/api/v1/auth/login", json={"email": "a@example.org", "password": "wrong-pass-1"}),
            "refresh-403": client.post("/api/v1/auth/refresh"),
            "refresh-401": client.post("/api/v1/auth/refresh", headers=CSRF),
            "logout-204": client.post("/api/v1/auth/logout", headers=CSRF),
            "me-200": client.get("/api/v1/auth/me", headers=h),
            "me-401": client.get("/api/v1/auth/me"),
            "courses-200": client.get("/api/v1/courses", headers=h),
            "course-201": client.post("/api/v1/courses", json={"name": "x"}, headers=h),
            "course-404": client.get("/api/v1/courses/nope", headers=h),
            "course-422": client.patch(f"/api/v1/courses/{self.a_course}", json={"owner_id": "x"}, headers=h),
        }

    def test_g1_m0_04_security_headers_on_every_m1_endpoint(self) -> None:
        with self.assertLogs("intellistudy.security", level="INFO"):
            responses = self.m1_responses()
        for name, response in responses.items():
            with self.subTest(endpoint=name):
                headers = response.headers  # type: ignore[attr-defined]
                self.assertEqual(headers["x-content-type-options"], "nosniff")
                self.assertEqual(headers["x-frame-options"], "DENY")
                self.assertEqual(headers["referrer-policy"], "no-referrer")
                self.assertEqual(headers["cache-control"], "no-store")
                self.assertIn("x-request-id", headers)

    def test_g1_m0_05_cors_only_for_approved_origins(self) -> None:
        for path in ("/api/v1/auth/refresh", "/api/v1/courses"):
            for origin in ("http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"):
                with self.subTest(path=path, origin=origin):
                    response = self.client().options(path, headers={
                        "Origin": origin, "Access-Control-Request-Method": "POST",
                        "Access-Control-Request-Headers": "X-Requested-With, Authorization, Content-Type"})
                    self.assertEqual(response.headers.get("access-control-allow-origin"), origin)
                    self.assertEqual(response.headers.get("access-control-allow-credentials"), "true")
            response = self.client().options(path, headers={"Origin": "https://evil.example",
                                                            "Access-Control-Request-Method": "POST"})
            self.assertNotIn("access-control-allow-origin", response.headers)

    def test_g1_m0_06_errors_are_problem_documents_without_leaks(self) -> None:
        with self.assertLogs("intellistudy.security", level="INFO"):
            responses = self.m1_responses()
        for name, response in responses.items():
            status = response.status_code  # type: ignore[attr-defined]
            if status < 400:
                continue
            with self.subTest(endpoint=name):
                self.assertEqual(response.headers["content-type"], "application/problem+json")  # type: ignore[attr-defined]
                text = response.text  # type: ignore[attr-defined]
                for leak in ("Traceback", "wrong-pass-1", "sqlalchemy", "/home/", "argon2"):
                    self.assertNotIn(leak, text)


if __name__ == "__main__":
    unittest.main()

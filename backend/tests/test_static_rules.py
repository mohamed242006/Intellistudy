"""Static architecture rules, checked on the source tree (contract VEC-03, VEC-04, OWN-03, SEC-02; matrix R-11, S-01).

These run on every change, so a later milestone cannot quietly add an unscoped store call to a route.
"""

from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend" / "app"

#: Modules allowed to construct or import the vector / parent stores (VEC-03).
STORE_OWNERS = {APP / "services" / "ai_container.py"}
STORE_MODULES = ("chromadb", "ai.vectorstore", "ai.storage")
#: Document-keyed helpers that skip user scope (VEC-04): never called from the API layer.
DOCUMENT_KEYED = {"list_ids", "list_record_hashes", "get_embeddings", "remove_document"}


def _modules(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


class StaticRuleTests(unittest.TestCase):
    def test_only_the_container_imports_the_stores(self) -> None:  # VEC-03
        offenders = []
        for path in _modules(APP):
            if path in STORE_OWNERS:
                continue
            bad = [m for m in _imports(ast.parse(path.read_text(encoding="utf-8")))
                   if m == "chromadb" or m.startswith(STORE_MODULES)]
            if bad:
                offenders.append(f"{path.relative_to(ROOT)}: {bad}")
        self.assertEqual(offenders, [])

    def test_api_layer_never_calls_document_keyed_store_helpers(self) -> None:  # VEC-04
        offenders = []
        for path in _modules(APP / "api"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in DOCUMENT_KEYED:
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} .{node.func.attr}()")
        self.assertEqual(offenders, [])

    def test_api_layer_never_does_unscoped_session_lookups(self) -> None:  # OWN-03
        offenders = []
        for path in _modules(APP / "api"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                        and isinstance(node.func.value, ast.Name) and node.func.value.id in {"session", "db"}):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno} session.get()")
        self.assertEqual(offenders, [])

    def test_no_hardcoded_secrets_in_backend_source(self) -> None:  # SEC-01 (coarse; gitleaks is the real check)
        offenders = []
        for path in _modules(APP):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    value = node.value
                    if value.startswith("sk-") and len(value) > 20 and "your" not in value:
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_no_env_file_is_tracked(self) -> None:  # SEC-02 / S-01
        try:
            tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git is not available")
        env_files = [f for f in tracked.splitlines() if Path(f).name == ".env" or (f.endswith(".env") and "example" not in f)]
        self.assertEqual(env_files, [])

    def test_env_example_has_no_real_values(self) -> None:
        example = ROOT / ".env.example"
        self.assertTrue(example.exists(), ".env.example documents the variables")
        for line in example.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if any(word in key for word in ("SECRET", "API_KEY")):
                self.assertIn(value.strip(), {"", "replace-with-output-of-secrets.token_urlsafe-32", "your-api-key-here"},
                              key)


if __name__ == "__main__":
    unittest.main()

"""Shared fixture for M2 tests: M1's users and courses, plus an injected AI container (deterministic embedder,
in-memory vector and parent stores) and an explicitly driven job runner. Parsing runs in the real sandbox child."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.chunking.config import EMBEDDING_MODEL
from ai.chunking.memory_store import InMemoryParentStore, InMemoryVectorStore
from backend.app.services.ai_container import AIContainer
from backend.tests.m1_base import M1Case
from backend.tests.m2_fixtures import MIME, docx_bytes, pdf_bytes, pptx_bytes
from tests.chunk_fixtures import FakeEmbedder


class M2Case(M1Case):
    def settings_overrides(self) -> dict[str, Any]:
        return {"worker_enabled": False, "chunk_tokenizer": "approx", "parse_timeout_seconds": 120}

    def make_ai(self) -> AIContainer:
        self.vectors = InMemoryVectorStore()
        self.parents = InMemoryParentStore()
        self.embedder = FakeEmbedder(model_name=EMBEDDING_MODEL)
        return AIContainer(self.settings, embedder=self.embedder, vector_store=self.vectors,
                           parent_store=self.parents)

    # ------------------------------------------------------------------------------------------ helpers
    def upload(self, client: Any, token: str, course_id: str, *files: tuple[str, bytes]) -> Any:
        parts = [("files", (name, data, MIME.get(name.rsplit(".", 1)[-1].lower(), "application/octet-stream")))
                 for name, data in files]
        return client.post(f"/api/v1/courses/{course_id}/documents", files=parts, headers=self.bearer(token))

    def upload_ok(self, client: Any, token: str, course_id: str, *files: tuple[str, bytes]) -> list[dict[str, Any]]:
        response = self.upload(client, token, course_id, *files)
        self.assertEqual(response.status_code, 202, response.text)
        return list(response.json()["documents"])

    def process(self) -> int:
        return int(self.app.state.jobs.run_pending())

    def document(self, token: str, document_id: str) -> dict[str, Any]:
        response = self.client().get(f"/api/v1/documents/{document_id}", headers=self.bearer(token))
        self.assertEqual(response.status_code, 200, response.text)
        return dict(response.json())

    def stored_dir(self, owner_id: str, document_id: str) -> Path:
        return Path(self.settings.storage_root).resolve() / owner_id / document_id

    def incoming_files(self) -> list[Path]:
        return list((Path(self.settings.storage_root).resolve() / ".incoming").glob("*"))

    def vector_records(self, document_id: str) -> list[dict[str, Any]]:
        """Every stored vector record (all collections) of ``document_id``."""
        out = []
        for collection in self.vectors._data.values():  # in-memory store internals, test only
            for record in collection.values():
                if record.metadata.get("document_uid") == document_id:
                    out.append({"id": record.id, **record.metadata})
        return out

    def parent_keys(self, document_id: str) -> set[str]:
        return set(self.parents.list_ids(document_uid=document_id))


SAMPLES = {
    "lecture.pdf": pdf_bytes,
    "notes.docx": docx_bytes,
    "slides.pptx": pptx_bytes,
}

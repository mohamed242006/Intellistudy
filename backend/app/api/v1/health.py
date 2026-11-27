"""``GET /api/v1/health``: unauthenticated liveness and readiness. Booleans and names only (contract SEC-08)."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.deps import get_ai, get_session, get_settings
from backend.app.core.config import Settings
from backend.app.db.migrate import current_revision, head_revision
from backend.app.services.ai_container import AIContainer

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class LLMStatus(BaseModel):
    configured: bool
    provider: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    #: "outdated": the database is behind this code's migrations (run python -m backend.app.db.migrate)
    database: Literal["ok", "error", "outdated"]
    llm: LLMStatus
    models: dict[str, bool]


@router.get("/health", response_model=HealthResponse)
def health(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
    ai: Annotated[AIContainer, Depends(get_ai)],
) -> HealthResponse:
    database: Literal["ok", "error", "outdated"]
    try:
        session.execute(text("SELECT 1"))
        # re-checked on every call, so the status recovers as soon as the migrations are applied
        outdated = current_revision(session.connection()) != head_revision()
        request.app.state.schema_outdated = "outdated" if outdated else None
        database = "outdated" if outdated else "ok"
    except Exception as exc:  # the reason goes to the log, never to the client
        logger.error("health: database check failed (%s)", type(exc).__name__)
        database = "error"
    provider = ai.provider
    name = getattr(provider, "name", "custom") if provider is not None else settings.llm_provider.value
    llm = LLMStatus(configured=provider is not None, provider=str(name))
    return HealthResponse(
        status="ok" if database == "ok" else "degraded", database=database, llm=llm, models=ai.status()
    )

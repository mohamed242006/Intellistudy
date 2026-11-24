"""``GET /api/v1/health``: unauthenticated liveness and readiness. Booleans and names only (contract SEC-08)."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.deps import get_ai, get_session, get_settings
from backend.app.core.config import Settings
from backend.app.services.ai_container import AIContainer

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class LLMStatus(BaseModel):
    configured: bool
    provider: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    llm: LLMStatus
    models: dict[str, bool]


@router.get("/health", response_model=HealthResponse)
def health(
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[Session, Depends(get_session)],
    ai: Annotated[AIContainer, Depends(get_ai)],
) -> HealthResponse:
    try:
        session.execute(text("SELECT 1"))
        database: Literal["ok", "error"] = "ok"
    except Exception as exc:  # the reason goes to the log, never to the client
        logger.error("health: database check failed (%s)", type(exc).__name__)
        database = "error"
    provider = ai.provider
    name = getattr(provider, "name", "custom") if provider is not None else settings.llm_provider.value
    llm = LLMStatus(configured=provider is not None, provider=str(name))
    return HealthResponse(
        status="ok" if database == "ok" else "degraded", database=database, llm=llm, models=ai.status()
    )

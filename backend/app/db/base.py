"""Declarative base and portable column types.

Portability rule (project decision 2026-11-24): the same models and migrations must run on SQLite (demo) and
PostgreSQL (production) with only ``DATABASE_URL`` changed. So: UUIDs are stored as 36-character strings, datetimes are
timezone-aware UTC on the way in and out, JSON uses SQLAlchemy's generic ``JSON``, and no dialect-specific SQL is used.
Constraint names follow one convention so Alembic diffs are stable on both back ends.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, String, TypeDecorator
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UTCDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes on every back end (SQLite drops the offset; this puts it back)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not allowed; use datetime.now(UTC)")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def new_uuid() -> str:
    """Server-generated UUIDv4 for every resource id (contract OWN-02)."""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class UUIDPrimaryKey:
    """Mixin: ``id`` is a server-generated UUIDv4 string (OWN-02)."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)


class Timestamps:
    """Mixin: ``created_at`` / ``updated_at`` in UTC."""

    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False)

"""ORM models. Importing this module registers every table on ``Base.metadata`` (used by Alembic).

Every model holding user data follows contract OWN-01: a non-nullable path to ``users.id``, and an ``owner_id`` on
tables addressed directly by id. Ids are server-generated UUIDv4 strings (OWN-02).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base, Timestamps, UTCDateTime, UUIDPrimaryKey

__all__ = ["Base", "Course", "RefreshToken", "Role", "User"]


class Role(StrEnum):
    STUDENT = "STUDENT"
    ADMIN = "ADMIN"


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    #: normalised (trimmed, lower-case) e-mail; unique, so e-mails are unique case-insensitively (G1-PWD-04)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=Role.STUDENT.value)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    #: access tokens with ``iat`` before this instant are rejected (logout-all, password change; JWT-05)
    tokens_valid_after: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class RefreshToken(UUIDPrimaryKey, Base):
    """One refresh token. Only the SHA-256 of the token is stored (RT-01)."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_family_id", "family_id"), Index("ix_refresh_tokens_user_id", "user_id"))

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    family_id: Mapped[str] = mapped_column(String(36), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)  # idle lifetime
    family_expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)  # absolute lifetime
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    replaced_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Course(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "courses"
    __table_args__ = (Index("ix_courses_owner_id", "owner_id"),)

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

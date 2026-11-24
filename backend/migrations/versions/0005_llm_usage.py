"""F-M3-05: the LLM usage ledger, the single source of truth for the daily token budget (contract UPL-16).

Existing messages are copied into the ledger so usage recorded before the upgrade still counts.

Revision ID: 0005_llm_usage
Revises: 0004_conversations_messages
Create Date: 2026-11-24
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.app.db.base import UTCDateTime

revision: str = "0005_llm_usage"
down_revision: str | None = "0004_conversations_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    usage = op.create_table(
        "llm_usage",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("feature", sa.String(16), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_llm_usage_owner_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_llm_usage"),
    )
    op.create_index("ix_llm_usage_owner_id_created_at", "llm_usage", ["owner_id", "created_at"])
    messages = sa.table("messages", sa.column("owner_id", sa.String), sa.column("model", sa.String),
                        sa.column("prompt_tokens", sa.Integer), sa.column("completion_tokens", sa.Integer),
                        sa.column("created_at", UTCDateTime()))
    rows = op.get_bind().execute(
        sa.select(messages).where((messages.c.prompt_tokens + messages.c.completion_tokens) > 0)).mappings().all()
    if rows:
        op.bulk_insert(usage, [{"id": str(uuid.uuid4()), "owner_id": r["owner_id"], "feature": "chat",
                                "model": r["model"], "prompt_tokens": r["prompt_tokens"],
                                "completion_tokens": r["completion_tokens"], "created_at": r["created_at"]}
                               for r in rows])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_owner_id_created_at", table_name="llm_usage")
    op.drop_table("llm_usage")

"""M3: conversations and messages.

Revision ID: 0004_conversations_messages
Revises: 0003_documents_jobs
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.app.db.base import UTCDateTime

revision: str = "0004_conversations_messages"
down_revision: str | None = "0003_documents_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_conversations_owner_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], name="fk_conversations_course_id_courses",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_owner_id", "conversations", ["owner_id"])
    op.create_index("ix_conversations_course_id", "conversations", ["course_id"])
    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("refusal_reason", sa.String(32), nullable=True),
        sa.Column("notice", sa.Text(), nullable=True),
        sa.Column("missing_terms", sa.JSON(), nullable=False),
        sa.Column("nearest", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("seconds", sa.Float(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], name="fk_messages_conversation_id_conversations",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name="fk_messages_owner_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_owner_id", "messages", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_owner_id", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_course_id", table_name="conversations")
    op.drop_index("ix_conversations_owner_id", table_name="conversations")
    op.drop_table("conversations")

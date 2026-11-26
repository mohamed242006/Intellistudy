"""Combined summaries: one summary grounded in several ready documents of a course.

Adds ``course_summaries`` and ``course_summary_sources`` and a nullable ``generation_jobs.course_summary_id``. Purely
additive: existing single-document summaries, quizzes and attempts are untouched and stay readable. The source table's
``document_id`` is not a foreign key (as ``quiz_sources``): deleting a document deletes the combined summaries built
from it in the service layer (deletion rule T-1), instead of a silent cascade.

Revision ID: 0008_course_summaries
Revises: 0007_quiz_attempts
Create Date: 2026-11-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.app.db.base import UTCDateTime

revision: str = "0008_course_summaries"
down_revision: str | None = "0007_quiz_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "course_summaries",
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("sections", sa.JSON(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("grounding", sa.JSON(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("generated_at", UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_course_summaries_owner_id", "course_summaries", ["owner_id"])
    op.create_index("ix_course_summaries_course_id", "course_summaries", ["course_id"])
    op.create_table(
        "course_summary_sources",
        sa.Column("summary_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["summary_id"], ["course_summaries.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_course_summary_sources_summary_id", "course_summary_sources", ["summary_id"])
    op.create_index("ix_course_summary_sources_document_id", "course_summary_sources", ["document_id"])
    with op.batch_alter_table("generation_jobs") as batch:
        batch.add_column(sa.Column("course_summary_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_generation_jobs_course_summary_id_course_summaries", "course_summaries", ["course_summary_id"],
                                 ["id"], ondelete="CASCADE")


def downgrade() -> None:
    with op.batch_alter_table("generation_jobs") as batch:
        batch.drop_constraint("fk_generation_jobs_course_summary_id_course_summaries", type_="foreignkey")
        batch.drop_column("course_summary_id")
    op.drop_index("ix_course_summary_sources_document_id", table_name="course_summary_sources")
    op.drop_index("ix_course_summary_sources_summary_id", table_name="course_summary_sources")
    op.drop_table("course_summary_sources")
    op.drop_index("ix_course_summaries_course_id", table_name="course_summaries")
    op.drop_index("ix_course_summaries_owner_id", table_name="course_summaries")
    op.drop_table("course_summaries")

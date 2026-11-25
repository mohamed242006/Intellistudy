"""M5: quiz attempts, saved answers and graded result snapshots; quiz generation number.

``attempt_answers.question_id`` and ``attempt_results.question_id`` are not foreign keys: a regeneration deletes the
questions, while an expired attempt keeps its answers and a submitted one its snapshot (M5 gate D5-3, D5-4). At most
one ``in_progress`` attempt per user and quiz (partial unique index, D5-2).

Revision ID: 0007_quiz_attempts
Revises: 0006_summaries_quizzes
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.app.db.base import UTCDateTime

revision: str = "0007_quiz_attempts"
down_revision: str | None = "0006_summaries_quizzes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IN_PROGRESS_ONLY = sa.text("status = 'in_progress'")


def upgrade() -> None:
    with op.batch_alter_table("quizzes") as batch:
        batch.add_column(sa.Column("generation", sa.Integer(), server_default="0", nullable=False))
    op.create_table(
        "quiz_attempts",
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("quiz_id", sa.String(length=36), nullable=False),
        sa.Column("quiz_generation", sa.Integer(), nullable=False),
        sa.Column("parent_attempt_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expired_reason", sa.String(length=32), nullable=True),
        sa.Column("question_ids", sa.JSON(), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=False),
        sa.Column("submitted_at", UTCDateTime(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("max_score", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quiz_attempts_owner_id_quiz_id", "quiz_attempts", ["owner_id", "quiz_id"])
    op.create_index("uq_quiz_attempts_in_progress", "quiz_attempts", ["owner_id", "quiz_id"], unique=True,
                    sqlite_where=IN_PROGRESS_ONLY, postgresql_where=IN_PROGRESS_ONLY)
    op.create_table(
        "attempt_answers",
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("choice", sa.Integer(), nullable=True),
        sa.Column("value", sa.Boolean(), nullable=True),
        sa.Column("saved_at", UTCDateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["quiz_attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "question_id", name="uq_attempt_answers_attempt_question"),
    )
    op.create_table(
        "attempt_results",
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("question_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=True),
        sa.Column("topic", sa.String(length=80), nullable=False),
        sa.Column("difficulty", sa.String(length=8), nullable=False),
        sa.Column("cognitive_level", sa.String(length=16), nullable=False),
        sa.Column("answer_choice", sa.Integer(), nullable=True),
        sa.Column("answer_value", sa.Boolean(), nullable=True),
        sa.Column("answered", sa.Boolean(), nullable=False),
        sa.Column("correct_choice", sa.Integer(), nullable=True),
        sa.Column("correct_value", sa.Boolean(), nullable=True),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("rationale_chosen", sa.Text(), nullable=True),
        sa.Column("citation", sa.JSON(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["quiz_attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "question_id", name="uq_attempt_results_attempt_question"),
    )


def downgrade() -> None:
    op.drop_table("attempt_results")
    op.drop_table("attempt_answers")
    op.drop_index("uq_quiz_attempts_in_progress", table_name="quiz_attempts")
    op.drop_index("ix_quiz_attempts_owner_id_quiz_id", table_name="quiz_attempts")
    op.drop_table("quiz_attempts")
    with op.batch_alter_table("quizzes") as batch:
        batch.drop_column("generation")

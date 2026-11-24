"""M4: summaries, quizzes (questions, answer keys, sources) and generation jobs.

The answer key has its own table (contract ISO-04). ``quiz_sources.document_id`` is not a foreign key: deleting a
document applies the M4 gate rules T-2 / T-3 instead of a cascade.

Revision ID: 0006_summaries_quizzes
Revises: 0005_llm_usage
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from backend.app.db.base import UTCDateTime

revision: str = '0006_summaries_quizzes'
down_revision: str | None = '0005_llm_usage'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('quizzes',
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('course_id', sa.String(length=36), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('invalid_reason', sa.String(length=32), nullable=True),
    sa.Column('error_code', sa.String(length=32), nullable=True),
    sa.Column('notice', sa.Text(), nullable=True),
    sa.Column('requested_count', sa.Integer(), nullable=False),
    sa.Column('question_count', sa.Integer(), nullable=False),
    sa.Column('question_types', sa.JSON(), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('generated_at', UTCDateTime(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], name=op.f('fk_quizzes_course_id_courses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_quizzes_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quizzes'))
    )
    with op.batch_alter_table('quizzes', schema=None) as batch_op:
        batch_op.create_index('ix_quizzes_course_id', ['course_id'], unique=False)
        batch_op.create_index('ix_quizzes_owner_id', ['owner_id'], unique=False)

    op.create_table('generation_jobs',
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('course_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=True),
    sa.Column('quiz_id', sa.String(length=36), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('error_code', sa.String(length=32), nullable=True),
    sa.Column('started_at', UTCDateTime(), nullable=True),
    sa.Column('finished_at', UTCDateTime(), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], name=op.f('fk_generation_jobs_course_id_courses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_generation_jobs_document_id_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_generation_jobs_owner_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.id'], name=op.f('fk_generation_jobs_quiz_id_quizzes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_generation_jobs'))
    )
    with op.batch_alter_table('generation_jobs', schema=None) as batch_op:
        batch_op.create_index('ix_generation_jobs_owner_id', ['owner_id'], unique=False)
        batch_op.create_index('ix_generation_jobs_status', ['status'], unique=False)

    op.create_table('quiz_questions',
    sa.Column('quiz_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('stem', sa.Text(), nullable=False),
    sa.Column('options', sa.JSON(), nullable=True),
    sa.Column('topic', sa.String(length=80), nullable=False),
    sa.Column('difficulty', sa.String(length=8), nullable=False),
    sa.Column('cognitive_level', sa.String(length=16), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_quiz_questions_owner_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.id'], name=op.f('fk_quiz_questions_quiz_id_quizzes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quiz_questions'))
    )
    with op.batch_alter_table('quiz_questions', schema=None) as batch_op:
        batch_op.create_index('ix_quiz_questions_quiz_id', ['quiz_id'], unique=False)

    op.create_table('quiz_sources',
    sa.Column('quiz_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_quiz_sources_owner_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.id'], name=op.f('fk_quiz_sources_quiz_id_quizzes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quiz_sources'))
    )
    with op.batch_alter_table('quiz_sources', schema=None) as batch_op:
        batch_op.create_index('ix_quiz_sources_document_id', ['document_id'], unique=False)
        batch_op.create_index('ix_quiz_sources_quiz_id', ['quiz_id'], unique=False)

    op.create_table('summaries',
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('course_id', sa.String(length=36), nullable=False),
    sa.Column('document_id', sa.String(length=36), nullable=False),
    sa.Column('sections', sa.JSON(), nullable=False),
    sa.Column('citations', sa.JSON(), nullable=False),
    sa.Column('warnings', sa.JSON(), nullable=False),
    sa.Column('grounding', sa.JSON(), nullable=False),
    sa.Column('chunk_count', sa.Integer(), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('generated_at', UTCDateTime(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', UTCDateTime(), nullable=False),
    sa.Column('updated_at', UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], name=op.f('fk_summaries_course_id_courses'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], name=op.f('fk_summaries_document_id_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_summaries_owner_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_summaries')),
    sa.UniqueConstraint('document_id', name=op.f('uq_summaries_document_id'))
    )
    with op.batch_alter_table('summaries', schema=None) as batch_op:
        batch_op.create_index('ix_summaries_owner_id', ['owner_id'], unique=False)

    op.create_table('quiz_answer_keys',
    sa.Column('question_id', sa.String(length=36), nullable=False),
    sa.Column('quiz_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('correct_index', sa.Integer(), nullable=True),
    sa.Column('correct_bool', sa.Boolean(), nullable=True),
    sa.Column('rationales', sa.JSON(), nullable=False),
    sa.Column('evidence', sa.Text(), nullable=False),
    sa.Column('source_chunk_ids', sa.JSON(), nullable=False),
    sa.Column('source_document_ids', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name=op.f('fk_quiz_answer_keys_owner_id_users'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['question_id'], ['quiz_questions.id'], name=op.f('fk_quiz_answer_keys_question_id_quiz_questions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.id'], name=op.f('fk_quiz_answer_keys_quiz_id_quizzes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_quiz_answer_keys')),
    sa.UniqueConstraint('question_id', name=op.f('uq_quiz_answer_keys_question_id'))
    )
    with op.batch_alter_table('quiz_answer_keys', schema=None) as batch_op:
        batch_op.create_index('ix_quiz_answer_keys_quiz_id', ['quiz_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('quiz_answer_keys', schema=None) as batch_op:
        batch_op.drop_index('ix_quiz_answer_keys_quiz_id')

    op.drop_table('quiz_answer_keys')
    with op.batch_alter_table('summaries', schema=None) as batch_op:
        batch_op.drop_index('ix_summaries_owner_id')

    op.drop_table('summaries')
    with op.batch_alter_table('quiz_sources', schema=None) as batch_op:
        batch_op.drop_index('ix_quiz_sources_quiz_id')
        batch_op.drop_index('ix_quiz_sources_document_id')

    op.drop_table('quiz_sources')
    with op.batch_alter_table('quiz_questions', schema=None) as batch_op:
        batch_op.drop_index('ix_quiz_questions_quiz_id')

    op.drop_table('quiz_questions')
    with op.batch_alter_table('generation_jobs', schema=None) as batch_op:
        batch_op.drop_index('ix_generation_jobs_status')
        batch_op.drop_index('ix_generation_jobs_owner_id')

    op.drop_table('generation_jobs')
    with op.batch_alter_table('quizzes', schema=None) as batch_op:
        batch_op.drop_index('ix_quizzes_owner_id')
        batch_op.drop_index('ix_quizzes_course_id')

    op.drop_table('quizzes')

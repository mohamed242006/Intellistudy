"""ORM models. Importing this module registers every table on ``Base.metadata`` (used by Alembic).

Every model holding user data follows contract OWN-01: a non-nullable path to ``users.id``, and an ``owner_id`` on
tables addressed directly by id. Ids are server-generated UUIDv4 strings (OWN-02).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base, Timestamps, UTCDateTime, UUIDPrimaryKey

__all__ = [
    "Base",
    "ChatState",
    "Conversation",
    "Course",
    "Document",
    "DocumentStatus",
    "GenerationJob",
    "GenerationKind",
    "JobStatus",
    "LlmUsage",
    "Message",
    "ProcessingJob",
    "Quiz",
    "QuizAnswerKey",
    "QuizQuestion",
    "QuizSource",
    "QuizStatus",
    "RefreshToken",
    "Role",
    "Summary",
    "UsageFeature",
    "User",
]


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


class DocumentStatus(StrEnum):
    """Processing lifecycle (FR-UPL-05). Only ``ready`` documents are retrievable (contract RET-05)."""

    QUEUED = "queued"
    VALIDATING = "validating"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"


class Document(UUIDPrimaryKey, Timestamps, Base):
    """An uploaded file. ``id`` is the ``document_uid`` used in the vector and parent stores (contract VEC-02)."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_owner_id", "owner_id"),
        Index("ix_documents_course_id", "course_id"),
        Index("ix_documents_course_sha", "course_id", "sha256"),
    )

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    #: display name only (FILE-02, FILE-08); never part of a path
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(8), nullable=False)  # pdf | docx | pptx (verified from content)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=DocumentStatus.QUEUED.value)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    warnings: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    ready_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingJob(UUIDPrimaryKey, Timestamps, Base):
    """A unit of background work. Carries ids only; the runner re-loads the document with its owner (OWN-10)."""

    __tablename__ = "processing_jobs"
    __table_args__ = (Index("ix_processing_jobs_status", "status"), Index("ix_processing_jobs_owner_id", "owner_id"))

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"),
                                             nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="ingest")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.QUEUED.value)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Conversation(UUIDPrimaryKey, Timestamps, Base):
    """A chat thread bound to one course (a message can never switch course; contract RET-02)."""

    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_owner_id", "owner_id"), Index("ix_conversations_course_id", "course_id"))

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)


class ChatState(StrEnum):
    """M3 gate state rule; precedence refused > partial > low_confidence > answered (confirmed 2026-11-24)."""

    REFUSED = "refused"
    PARTIAL = "partial"
    LOW_CONFIDENCE = "low_confidence"
    ANSWERED = "answered"


class Message(UUIDPrimaryKey, Timestamps, Base):
    """One question and its answer, stored with its citations (FR-CIT-05)."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_id", "conversation_id"), Index("ix_messages_owner_id", "owner_id"))

    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id", ondelete="CASCADE"),
                                                 nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    refusal_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notice: Mapped[str | None] = mapped_column(Text, nullable=True)
    missing_terms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    nearest: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class UsageFeature(StrEnum):
    CHAT = "chat"
    SUMMARY = "summary"
    QUIZ = "quiz"


class LlmUsage(UUIDPrimaryKey, Base):
    """The daily token budget's single source of truth (contract UPL-16, finding F-M3-05): one row per provider call.

    Deliberately linked to nothing but the user: deleting conversations, messages, summaries, quizzes, documents or
    courses never removes usage. Holds no content (no question, answer or document text)."""

    __tablename__ = "llm_usage"
    __table_args__ = (Index("ix_llm_usage_owner_id_created_at", "owner_id", "created_at"),)

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    feature: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


# --------------------------------------------------------------------------------------------- M4: generation
class GenerationKind(StrEnum):
    SUMMARY = "summary"
    QUIZ = "quiz"


class GenerationJob(UUIDPrimaryKey, Timestamps, Base):
    """Background summary / quiz generation (M4 gate D-2). Carries ids only; the runner re-loads everything with its
    owner. A summary job belongs to its document, a quiz job to its quiz: deleting either deletes the job (T-1..T-3)."""

    __tablename__ = "generation_jobs"
    __table_args__ = (Index("ix_generation_jobs_status", "status"), Index("ix_generation_jobs_owner_id", "owner_id"))

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"),
                                                    nullable=True)
    quiz_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.QUEUED.value)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Summary(UUIDPrimaryKey, Timestamps, Base):
    """The stored summary of one document (T-4, D-1). Exists only once a generation succeeded; replaced atomically
    by a successful regeneration (G4-CAC-03); deleted with its document (T-1)."""

    __tablename__ = "summaries"
    __table_args__ = (Index("ix_summaries_owner_id", "owner_id"),)

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"),
                                             nullable=False, unique=True)
    sections: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    citations: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    grounding: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class QuizStatus(StrEnum):
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"
    INVALID = "invalid"


class Quiz(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "quizzes"
    __table_args__ = (Index("ix_quizzes_owner_id", "owner_id"), Index("ix_quizzes_course_id", "course_id"))

    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=QuizStatus.GENERATING.value)
    invalid_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notice: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class QuizSource(UUIDPrimaryKey, Base):
    """A source document of a quiz. ``document_id`` is deliberately not a foreign key: deleting the document runs the
    T-2 / T-3 rules (delete or invalidate the quiz) instead of a silent cascade."""

    __tablename__ = "quiz_sources"
    __table_args__ = (Index("ix_quiz_sources_quiz_id", "quiz_id"), Index("ix_quiz_sources_document_id", "document_id"))

    quiz_id: Mapped[str] = mapped_column(String(36), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)


class QuizQuestion(UUIDPrimaryKey, Base):
    """The public part of a question. The answer lives only in :class:`QuizAnswerKey` (contract ISO-04)."""

    __tablename__ = "quiz_questions"
    __table_args__ = (Index("ix_quiz_questions_quiz_id", "quiz_id"),)

    quiz_id: Mapped[str] = mapped_column(String(36), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(8), nullable=False)
    cognitive_level: Mapped[str] = mapped_column(String(16), nullable=False)


class QuizAnswerKey(UUIDPrimaryKey, Base):
    """Correct answer, rationales, evidence and sources of one question. Never serialised by the API in M4 (ISO-04);
    M5 grading reads it."""

    __tablename__ = "quiz_answer_keys"
    __table_args__ = (Index("ix_quiz_answer_keys_quiz_id", "quiz_id"),)

    question_id: Mapped[str] = mapped_column(String(36), ForeignKey("quiz_questions.id", ondelete="CASCADE"),
                                             nullable=False, unique=True)
    quiz_id: Mapped[str] = mapped_column(String(36), ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    correct_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correct_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rationales: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    source_chunk_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_document_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)

"""Grounded chat: conversations and messages (M3; docs/M3_RELEASE_GATE.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from pydantic import BaseModel, Field, StringConstraints

from backend.app.api.deps import CurrentUser, DbSession
from backend.app.api.v1.schemas import RequestModel
from backend.app.db.models import Conversation, Message
from backend.app.services.chat import MAX_QUESTION_CHARS, ChatService

router = APIRouter(tags=["chat"])

Id = Annotated[str, Path()]


def get_chat(request: Request) -> ChatService:
    service: ChatService = request.app.state.chat
    return service


Chat = Annotated[ChatService, Depends(get_chat)]


class ConversationCreate(RequestModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class MessageCreate(RequestModel):
    """Only the question and an optional document selection; scope fields are rejected (OWN-08, RET-07)."""

    question: Annotated[str, StringConstraints(min_length=1, max_length=MAX_QUESTION_CHARS)]
    document_ids: Annotated[list[str], Field(min_length=1, max_length=100)] | None = None


class SourceOut(BaseModel):
    document_id: str
    file_name: str
    citation_label: str
    page: int | None
    slide: int | None
    passage: str


class CitationOut(SourceOut):
    number: int
    context: str
    low_confidence: bool
    generated: bool


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    question: str
    state: str
    text: str
    citations: list[CitationOut]
    refusal_reason: str | None
    notice: str | None
    missing_terms: list[str]
    nearest: list[SourceOut]
    warnings: list[str]
    model: str
    seconds: float
    created_at: datetime


class ConversationOut(BaseModel):
    id: str
    course_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationList(BaseModel):
    items: list[ConversationOut]
    limit: int
    offset: int


def _conversation(c: Conversation) -> dict[str, object]:
    return {"id": c.id, "course_id": c.course_id, "title": c.title, "created_at": c.created_at,
            "updated_at": c.updated_at}


def _message(m: Message) -> MessageOut:
    return MessageOut(
        id=m.id, conversation_id=m.conversation_id, question=m.question, state=m.state, text=m.text,
        citations=[CitationOut(**c) for c in m.citations],
        refusal_reason=m.refusal_reason, notice=m.notice, missing_terms=list(m.missing_terms),
        nearest=[SourceOut(**s) for s in m.nearest],
        warnings=list(m.warnings), model=m.model, seconds=m.seconds, created_at=m.created_at,
    )


@router.post("/courses/{course_id}/conversations", status_code=status.HTTP_201_CREATED, response_model=ConversationOut)
def create_conversation(course_id: Id, body: ConversationCreate, user: CurrentUser, session: DbSession,
                        chat: Chat) -> ConversationOut:
    return ConversationOut(**_conversation(chat.create_conversation(session, user, course_id, body.title)))


@router.get("/courses/{course_id}/conversations", response_model=ConversationList)
def list_conversations(course_id: Id, user: CurrentUser, session: DbSession, chat: Chat,
                       limit: Annotated[int, Query(ge=1, le=100)] = 50,
                       offset: Annotated[int, Query(ge=0, le=100_000)] = 0) -> ConversationList:
    items = chat.list_conversations(session, user, course_id, limit=limit, offset=offset)
    return ConversationList(items=[ConversationOut(**_conversation(c)) for c in items], limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: Id, user: CurrentUser, session: DbSession, chat: Chat) -> ConversationDetail:
    conversation, messages = chat.get_conversation(session, user, conversation_id)
    return ConversationDetail(**_conversation(conversation), messages=[_message(m) for m in messages])


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(conversation_id: Id, user: CurrentUser, session: DbSession, chat: Chat) -> Response:
    chat.delete_conversation(session, user, conversation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_201_CREATED,
             response_model=MessageOut)
def ask(conversation_id: Id, body: MessageCreate, user: CurrentUser, session: DbSession, chat: Chat) -> MessageOut:
    return _message(chat.ask(session, user, conversation_id, body.question, body.document_ids))

"""``/api/v1/courses``: course workspaces. Every lookup by id goes through ``get_owned`` (contract OWN-03).

Path ids are plain strings on purpose: a malformed id must produce the same 404 as a missing or foreign one
(OWN-04, G1-IDOR-04), not FastAPI's 422.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response, status

from backend.app.api.deps import CurrentUser, DbSession
from backend.app.api.v1.schemas import CourseCreate, CourseList, CourseOut, CourseUpdate
from backend.app.db.models import Course
from backend.app.services import courses as course_service
from backend.app.services.documents import DocumentService

router = APIRouter(prefix="/courses", tags=["courses"])

CourseId = Annotated[str, Path()]  # no length/format constraint here: get_owned turns every bad id into a 404


def _out(course: Course) -> CourseOut:
    return CourseOut(id=course.id, name=course.name, code=course.code, description=course.description,
                     archived=course.archived, created_at=course.created_at, updated_at=course.updated_at)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CourseOut)
def create_course(body: CourseCreate, user: CurrentUser, session: DbSession) -> CourseOut:
    course = course_service.create_course(session, user, name=body.name, code=body.code, description=body.description)
    return _out(course)


@router.get("", response_model=CourseList)
def list_courses(
    user: CurrentUser,
    session: DbSession,
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> CourseList:
    items = course_service.list_courses(session, user, include_archived=include_archived, limit=limit, offset=offset)
    return CourseList(items=[_out(c) for c in items], limit=limit, offset=offset)


@router.get("/{course_id}", response_model=CourseOut)
def get_course(course_id: CourseId, user: CurrentUser, session: DbSession) -> CourseOut:
    return _out(course_service.get_course(session, user, course_id))


@router.patch("/{course_id}", response_model=CourseOut)
def update_course(course_id: CourseId, body: CourseUpdate, user: CurrentUser, session: DbSession) -> CourseOut:
    changes = body.model_dump(exclude_unset=True)
    return _out(course_service.update_course(session, user, course_id, changes))


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course(course_id: CourseId, request: Request, user: CurrentUser, session: DbSession) -> Response:
    """ISO-03: documents (vectors, parents, files, rows) first, then the course."""
    documents: DocumentService = request.app.state.documents
    documents.delete_course(session, user, course_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

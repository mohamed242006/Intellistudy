"""Course workspaces (FR-CRS-01/02/03). Every access is owner-scoped (contract OWN-03, OWN-07)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import Course, User
from backend.app.services.ownership import get_owned

RESOURCE = "course"


def create_course(session: Session, owner: User, *, name: str, code: str | None, description: str | None) -> Course:
    course = Course(owner_id=owner.id, name=name, code=code, description=description, archived=False)
    session.add(course)
    session.commit()
    return course


def list_courses(session: Session, owner: User, *, include_archived: bool, limit: int, offset: int) -> list[Course]:
    query = select(Course).where(Course.owner_id == owner.id)  # OWN-07: the filter is part of the query
    if not include_archived:
        query = query.where(Course.archived.is_(False))
    query = query.order_by(Course.created_at.desc(), Course.id).limit(limit).offset(offset)
    return list(session.scalars(query))


def get_course(session: Session, owner: User, course_id: str) -> Course:
    return get_owned(session, Course, course_id, owner.id, resource=RESOURCE)


def update_course(session: Session, owner: User, course_id: str, changes: dict[str, object]) -> Course:
    course = get_owned(session, Course, course_id, owner.id, resource=RESOURCE)
    for field in ("name", "code", "description", "archived"):  # explicit allowlist; ownership is never writable
        if field in changes:
            setattr(course, field, changes[field])
    session.commit()
    return course

# Course deletion lives in DocumentService.delete_course: since M2 a course owns documents, whose vectors, parents and
# files must be removed first (ISO-03).

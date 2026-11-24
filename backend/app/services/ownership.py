"""The single ownership choke point (contract OWN-03, OWN-04, OWN-05).

Every read, update or delete of a user resource by id goes through :func:`get_owned`:

* the id must be a canonical (lower-case) UUID string; anything else is "not found" (no 422, no 500; G1-IDOR-04);
* the row is selected by id **and** ``owner_id`` in one statement (OWN-03);
* a missing row and another user's row produce the same :func:`not_found` error (OWN-04);
* only when the id exists under another owner is a security event written (OWN-05); random ids log nothing.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.errors import ApiError, not_found
from backend.app.core.logging import security_event
from backend.app.db.base import Base

CANONICAL_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def is_canonical_id(raw_id: str) -> bool:
    return bool(CANONICAL_UUID.fullmatch(raw_id))


def get_owned[T: Base](session: Session, model: type[T], raw_id: str, user_id: str, *, resource: str) -> T:
    """The row ``raw_id`` of ``model`` owned by ``user_id``, or :class:`ApiError` 404.

    ``model`` must have ``id`` and ``owner_id`` columns (OWN-01); a model without ``owner_id`` fails loudly here.
    """
    if not isinstance(raw_id, str) or not is_canonical_id(raw_id):
        raise not_found()
    table: Any = model  # column attributes of a mapped class
    row = session.scalars(select(model).where(table.id == raw_id, table.owner_id == user_id)).one_or_none()
    if row is not None:
        return row
    if session.scalar(select(table.id).where(table.id == raw_id)) is not None:
        security_event("ownership_mismatch", user_id=user_id, resource=resource, resource_id=raw_id)
    raise not_found()


__all__ = ["ApiError", "get_owned", "is_canonical_id"]

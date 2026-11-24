"""Request and response models. Every request model forbids unknown fields (contract OWN-08): ownership fields
such as ``owner_id`` are rejected with 422, never silently ignored."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


# ------------------------------------------------------------------------------------------------- auth
class RegisterRequest(RequestModel):
    email: Annotated[str, StringConstraints(min_length=3, max_length=320)]
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class LoginRequest(RequestModel):
    email: Annotated[str, StringConstraints(min_length=1, max_length=320)]
    password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class ChangePasswordRequest(RequestModel):
    current_password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    new_password: Annotated[str, StringConstraints(min_length=1, max_length=1024)]


class TokenResponse(BaseModel):
    """The refresh token is never in a response body (RT-02); it travels only in its cookie."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    created_at: datetime


# ---------------------------------------------------------------------------------------------- courses
CourseName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
CourseCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
CourseDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class CourseCreate(RequestModel):
    name: CourseName
    code: CourseCode | None = None
    description: CourseDescription | None = None


class CourseUpdate(RequestModel):
    name: CourseName | None = None
    code: CourseCode | None = None
    description: CourseDescription | None = None
    archived: bool | None = None

    @field_validator("name", "archived")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("may not be null")
        return value


class CourseOut(BaseModel):
    id: str
    name: str
    code: str | None
    description: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime


class CourseList(BaseModel):
    """Only the caller's own courses; no total that could count anyone else's (G1-ISO-04)."""

    items: list[CourseOut]
    limit: int
    offset: int

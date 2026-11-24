"""``/api/v1/auth``: register, login, refresh, logout, logout-all, me, change-password (contract sections 6-7)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from backend.app.api.deps import (
    CurrentUser,
    DbSession,
    get_auth,
    get_rate_limiter,
    require_csrf_guard,
)
from backend.app.api.v1.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from backend.app.core.errors import ApiError
from backend.app.core.ratelimit import LIMITS, RateLimiter, client_ip, enforce
from backend.app.db.models import User
from backend.app.services.auth import AuthService, SessionTokens, normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])

#: ``__Secure-`` prefix: browsers accept it only with ``Secure`` (RT-02).
REFRESH_COOKIE = "__Secure-is_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"

Auth = Annotated[AuthService, Depends(get_auth)]
Limiter = Annotated[RateLimiter, Depends(get_rate_limiter)]


def _set_refresh_cookie(response: Response, tokens: SessionTokens) -> None:
    response.set_cookie(
        REFRESH_COOKIE, tokens.refresh_token, max_age=tokens.refresh_max_age, path=REFRESH_COOKIE_PATH,
        secure=True, httponly=True, samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, secure=True, httponly=True, samesite="strict")


def _token_response(response: Response, tokens: SessionTokens) -> TokenResponse:
    _set_refresh_cookie(response, tokens)
    return TokenResponse(access_token=tokens.access.token, expires_in=tokens.access.expires_in)


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name, role=user.role, created_at=user.created_at)


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
def register(body: RegisterRequest, request: Request, session: DbSession, auth: Auth, limiter: Limiter) -> UserOut:
    enforce(limiter, LIMITS["register:ip"], client_ip(request))
    user = auth.register(session, email=body.email, name=body.name, password=body.password)
    return _user_out(user)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, response: Response, session: DbSession, auth: Auth,
          limiter: Limiter) -> TokenResponse:
    ip = client_ip(request)
    enforce(limiter, LIMITS["login:ip"], ip)
    enforce(limiter, LIMITS["login:account"], normalize_email(body.email), actor=ip)
    tokens = auth.login(session, email=body.email, password=body.password, ip=ip)
    return _token_response(response, tokens)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(require_csrf_guard)])
def refresh(request: Request, response: Response, session: DbSession, auth: Auth) -> TokenResponse:
    try:
        tokens = auth.refresh(session, request.cookies.get(REFRESH_COOKIE))
    except ApiError as exc:
        if exc.status == status.HTTP_401_UNAUTHORIZED:  # every refresh failure clears the cookie (RT-05)
            exc.headers = {**exc.headers, "Set-Cookie": _expired_cookie_header()}
        raise
    return _token_response(response, tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf_guard)])
def logout(request: Request, session: DbSession, auth: Auth) -> Response:
    auth.logout(session, request.cookies.get(REFRESH_COOKIE))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(user: CurrentUser, session: DbSession, auth: Auth) -> Response:
    auth.logout_all(session, user)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)


@router.post("/change-password", response_model=TokenResponse)
def change_password(body: ChangePasswordRequest, request: Request, response: Response, user: CurrentUser,
                    session: DbSession, auth: Auth) -> TokenResponse:
    tokens = auth.change_password(session, user, current=body.current_password, new=body.new_password,
                                  ip=client_ip(request))
    return _token_response(response, tokens)


def _expired_cookie_header() -> str:
    probe = Response()
    _clear_refresh_cookie(probe)
    return probe.headers["set-cookie"]

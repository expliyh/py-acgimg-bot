"""Login, session and password endpoints for the Web administration console."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from services import admin_auth

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class AdminIdentity(BaseModel):
    authenticated: bool
    username: str | None = None


class LoginResponse(AdminIdentity):
    authenticated: bool = True


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookie(response: Response, request: Request, username: str) -> None:
    response.set_cookie(
        key=admin_auth.SESSION_COOKIE_NAME,
        value=admin_auth.create_session_token(username),
        max_age=admin_auth.cookie_max_age(),
        httponly=True,
        secure=admin_auth.cookie_secure(request),
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, request: Request, response: Response) -> LoginResponse:
    """Authenticate an administrator and set an HttpOnly session cookie."""

    key = _client_key(request)
    retry_after = admin_auth.login_retry_after(key)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"登录尝试过于频繁，请在 {retry_after} 秒后重试",
            headers={"Retry-After": str(retry_after)},
        )

    credentials = await admin_auth.load_credentials()
    username_ok = payload.username == credentials.username
    password_ok = admin_auth.verify_password(payload.password, credentials.password_hash)
    if not (username_ok and password_ok):
        admin_auth.record_login_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    admin_auth.clear_login_failures(key)
    _set_session_cookie(response, request, credentials.username)
    return LoginResponse(username=credentials.username)


@router.post("/logout", response_model=AdminIdentity)
async def logout(request: Request, response: Response) -> AdminIdentity:
    """Clear the current session cookie."""

    response.delete_cookie(
        key=admin_auth.SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        secure=admin_auth.cookie_secure(request),
        samesite="lax",
    )
    return AdminIdentity(authenticated=False)


@router.get("/me", response_model=AdminIdentity)
async def current_admin(request: Request) -> AdminIdentity:
    """Return the identity carried by the current session cookie."""

    username = admin_auth.current_username(request)
    return AdminIdentity(authenticated=bool(username), username=username)


@router.post("/password", response_model=LoginResponse)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    username: str = Depends(admin_auth.require_admin),
) -> LoginResponse:
    """Change the database-managed password and refresh the session."""

    credentials = await admin_auth.load_credentials()
    if not admin_auth.verify_password(payload.current_password, credentials.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前密码不正确",
        )

    credentials = await admin_auth.save_password(payload.new_password)
    _set_session_cookie(response, request, credentials.username)
    return LoginResponse(username=credentials.username)

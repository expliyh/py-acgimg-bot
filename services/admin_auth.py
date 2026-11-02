"""Authentication and signed sessions for the administrative web console.

Credentials come from ``ADMIN_USERNAME``/``ADMIN_PASSWORD`` when the password
environment variable is set. Otherwise they are read from the database, and a
random initial password is generated and stored on first startup.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request, status

from registries import config_registry

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "acgimg_admin_session"
DEFAULT_SESSION_TTL_SECONDS = 12 * 60 * 60
PASSWORD_HASH_ITERATIONS = 310_000
_INITIAL_PASSWORD_FILE = Path(__file__).resolve().parents[1] / "storage" / "admin-initial-password.txt"

_ADMIN_USERNAME_KEY = "admin_username"
_ADMIN_PASSWORD_HASH_KEY = "admin_password_hash"


@dataclass(frozen=True)
class AdminCredentials:
    username: str
    password_hash: str
    source: str


_credentials: AdminCredentials | None = None
_signing_key: bytes | None = None


def _env_password() -> str | None:
    value = os.getenv("ADMIN_PASSWORD")
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_username() -> str:
    return (os.getenv("ADMIN_USERNAME") or "admin").strip() or "admin"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def hash_password(password: str) -> str:
    """Return a salted PBKDF2-SHA256 password hash."""

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_HASH_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def verify_password(password: str, encoded: str | None) -> bool:
    """Verify a password against a hash produced by :func:`hash_password`."""

    if not encoded:
        return False
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(digest_text + "=" * (-len(digest_text) % 4))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(actual, expected)


def _set_credentials(credentials: AdminCredentials) -> None:
    global _credentials, _signing_key
    _credentials = credentials
    _signing_key = hashlib.sha256(
        b"acgimg-admin-session-v1:" + credentials.password_hash.encode("utf-8")
    ).digest()


def session_ttl_seconds() -> int:
    try:
        value = int(os.getenv("ADMIN_SESSION_TTL_SECONDS", str(DEFAULT_SESSION_TTL_SECONDS)))
    except ValueError:
        value = DEFAULT_SESSION_TTL_SECONDS
    return max(300, min(value, 30 * 24 * 60 * 60))


def _write_initial_password(username: str, password: str) -> None:
    try:
        _INITIAL_PASSWORD_FILE.parent.mkdir(parents=True, exist_ok=True)
        _INITIAL_PASSWORD_FILE.write_text(
            "初始 Web 管理端登录信息\n"
            f"用户名: {username}\n"
            f"密码: {password}\n"
            "登录后请在右上角账号菜单中修改密码，并删除此文件。\n",
            encoding="utf-8",
        )
        try:
            _INITIAL_PASSWORD_FILE.chmod(0o600)
        except OSError:
            pass
        logger.warning(
            "已生成 Web 管理端初始密码，请查看 %s 后尽快修改密码",
            _INITIAL_PASSWORD_FILE,
        )
    except OSError:
        logger.exception("无法写入 Web 管理端初始密码文件")


async def ensure_admin_credentials() -> AdminCredentials:
    """Load admin credentials, creating a random initial password if needed."""

    global _credentials

    env_password = _env_password()
    if env_password:
        credentials = AdminCredentials(_env_username(), hash_password(env_password), "env")
        _set_credentials(credentials)
        return credentials

    if _credentials is not None and _credentials.source == "database":
        return _credentials

    stored_username = await config_registry.get_config(_ADMIN_USERNAME_KEY)
    stored_hash = await config_registry.get_config(_ADMIN_PASSWORD_HASH_KEY)
    if isinstance(stored_hash, str) and stored_hash:
        credentials = AdminCredentials(
            _env_username()
            if os.getenv("ADMIN_USERNAME")
            else str(stored_username) if isinstance(stored_username, str) and stored_username else _env_username(),
            stored_hash,
            "database",
        )
        _set_credentials(credentials)
        return credentials

    username = (
        _env_username()
        if os.getenv("ADMIN_USERNAME")
        else str(stored_username) if isinstance(stored_username, str) and stored_username else _env_username()
    )
    generated_password = secrets.token_urlsafe(18)
    generated_hash = hash_password(generated_password)
    await config_registry.update_configs({
        _ADMIN_USERNAME_KEY: username,
        _ADMIN_PASSWORD_HASH_KEY: generated_hash,
    })
    _write_initial_password(username, generated_password)
    credentials = AdminCredentials(username, generated_hash, "database")
    _set_credentials(credentials)
    return credentials


async def load_credentials() -> AdminCredentials:
    """Return current credentials, refreshing env-managed values when changed."""

    return await ensure_admin_credentials()


async def save_password(new_password: str) -> AdminCredentials:
    """Persist a new password for database-managed credentials."""

    global _credentials

    if _credentials is None:
        await ensure_admin_credentials()
    if _credentials is not None and _credentials.source == "env":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="密码由 ADMIN_PASSWORD 环境变量管理，请修改环境变量",
        )

    username = _credentials.username if _credentials else _env_username()
    new_hash = hash_password(new_password)
    await config_registry.update_configs({
        _ADMIN_USERNAME_KEY: username,
        _ADMIN_PASSWORD_HASH_KEY: new_hash,
    })
    credentials = AdminCredentials(username, new_hash, "database")
    _set_credentials(credentials)
    return credentials


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _current_signing_key() -> bytes | None:
    if _signing_key is not None:
        return _signing_key
    password = _env_password()
    if password:
        _set_credentials(AdminCredentials(_env_username(), hash_password(password), "env"))
        return _signing_key
    return None


def create_session_token(username: str) -> str:
    """Create a signed, self-contained session token for a cookie."""

    key = _current_signing_key()
    if key is None:
        raise RuntimeError("管理员凭据尚未初始化")
    issued_at = int(time.time())
    payload = {
        "sub": username,
        "iat": issued_at,
        "exp": issued_at + session_ttl_seconds(),
        "nonce": secrets.token_urlsafe(9),
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    body = _b64encode(raw)
    signature = _b64encode(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify_session_token(token: str | None) -> str | None:
    """Validate a session token and return its username, or ``None``."""

    if not token:
        return None
    key = _current_signing_key()
    if key is None:
        return None
    try:
        body, signature = token.split(".", 1)
        expected = _b64encode(hmac.new(key, body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_b64decode(body).decode("utf-8"))
        subject = payload.get("sub")
        expires_at = int(payload.get("exp", 0))
        issued_at = int(payload.get("iat", 0))
    except (TypeError, ValueError, AttributeError, UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        return None
    if not isinstance(subject, str):
        return None
    now = int(time.time())
    if expires_at <= now or issued_at > now + 60:
        return None
    if _credentials is not None and subject != _credentials.username:
        return None
    return subject


def current_username(request: Request) -> str | None:
    return verify_session_token(request.cookies.get(SESSION_COOKIE_NAME))


async def require_admin(request: Request) -> str:
    """FastAPI dependency that rejects requests without a valid session."""

    username = current_username(request)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录管理端",
        )
    return username


def cookie_secure(request: Request) -> bool:
    configured = os.getenv("ADMIN_COOKIE_SECURE")
    if configured is not None:
        return _env_bool("ADMIN_COOKIE_SECURE", False)
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    return request.url.scheme == "https" or forwarded == "https"


def cookie_max_age() -> int:
    return session_ttl_seconds()


# --- Login rate limiting -------------------------------------------------

_LOGIN_WINDOW_SECONDS = 300
_LOGIN_MAX_ATTEMPTS = 5
_login_attempts: dict[str, list[float]] = {}


def _rate_limit_window() -> int:
    try:
        return max(30, int(os.getenv("ADMIN_LOGIN_WINDOW_SECONDS", str(_LOGIN_WINDOW_SECONDS))))
    except ValueError:
        return _LOGIN_WINDOW_SECONDS


def _rate_limit_max_attempts() -> int:
    try:
        return max(1, int(os.getenv("ADMIN_LOGIN_MAX_ATTEMPTS", str(_LOGIN_MAX_ATTEMPTS))))
    except ValueError:
        return _LOGIN_MAX_ATTEMPTS


def _prune_attempts(now: float) -> None:
    window = _rate_limit_window()
    for key, values in list(_login_attempts.items()):
        remaining = [value for value in values if now - value < window]
        if remaining:
            _login_attempts[key] = remaining
        else:
            _login_attempts.pop(key, None)


def login_retry_after(key: str) -> int:
    """Return remaining lockout seconds for ``key``, or ``0`` when allowed."""

    now = time.time()
    _prune_attempts(now)
    attempts = _login_attempts.get(key, [])
    if len(attempts) < _rate_limit_max_attempts():
        return 0
    return max(1, int(_rate_limit_window() - (now - attempts[0])))


def record_login_failure(key: str) -> None:
    now = time.time()
    _prune_attempts(now)
    _login_attempts.setdefault(key, []).append(now)


def clear_login_failures(key: str) -> None:
    _login_attempts.pop(key, None)


def reset_login_rate_limits() -> None:
    """Clear in-memory login throttling state (used by tests)."""

    _login_attempts.clear()


__all__ = [
    "SESSION_COOKIE_NAME",
    "AdminCredentials",
    "clear_login_failures",
    "cookie_max_age",
    "cookie_secure",
    "create_session_token",
    "current_username",
    "ensure_admin_credentials",
    "hash_password",
    "load_credentials",
    "login_retry_after",
    "record_login_failure",
    "require_admin",
    "reset_login_rate_limits",
    "save_password",
    "session_ttl_seconds",
    "verify_password",
    "verify_session_token",
]

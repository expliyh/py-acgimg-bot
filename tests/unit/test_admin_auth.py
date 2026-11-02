"""Password hashing, signed sessions and initial credential generation."""

from __future__ import annotations

import time

import pytest

from services import admin_auth


def test_password_hash_is_salted_and_verifiable():
    first = admin_auth.hash_password("correct horse battery staple")
    second = admin_auth.hash_password("correct horse battery staple")

    assert first != second
    assert first.startswith("pbkdf2_sha256$")
    assert admin_auth.verify_password("correct horse battery staple", first)
    assert not admin_auth.verify_password("wrong password", first)
    assert not admin_auth.verify_password("anything", "not-a-valid-hash")


@pytest.mark.asyncio
async def test_session_token_round_trip_and_tampering(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "session-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "session-password")
    credentials = await admin_auth.ensure_admin_credentials()

    token = admin_auth.create_session_token(credentials.username)
    assert admin_auth.verify_session_token(token) == "session-admin"
    assert admin_auth.verify_session_token(token + "x") is None
    assert admin_auth.verify_session_token(token.replace(".", ".x", 1)) is None
    assert admin_auth.verify_session_token(None) is None


@pytest.mark.asyncio
async def test_session_token_expires(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "expiry-admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "expiry-password")
    credentials = await admin_auth.ensure_admin_credentials()
    token = admin_auth.create_session_token(credentials.username)
    future = time.time() + admin_auth.session_ttl_seconds() + 5

    monkeypatch.setattr(time, "time", lambda: future)
    assert admin_auth.verify_session_token(token) is None


@pytest.mark.asyncio
async def test_missing_credentials_generate_a_persisted_initial_password(monkeypatch, tmp_path):
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_USERNAME", "generated-admin")
    monkeypatch.setattr(admin_auth, "_credentials", None)
    monkeypatch.setattr(admin_auth, "_signing_key", None)
    password_file = tmp_path / "admin-initial-password.txt"
    monkeypatch.setattr(admin_auth, "_INITIAL_PASSWORD_FILE", password_file)

    credentials = await admin_auth.ensure_admin_credentials()

    assert credentials.source == "database"
    assert credentials.username == "generated-admin"
    assert password_file.exists()
    contents = password_file.read_text(encoding="utf-8")
    assert "用户名: generated-admin" in contents
    generated_password = next(
        line.split(":", 1)[1].strip() for line in contents.splitlines() if line.startswith("密码:")
    )
    assert admin_auth.verify_password(generated_password, credentials.password_hash)
    from registries import config_registry

    assert await config_registry.get_config("admin_password_hash") == credentials.password_hash

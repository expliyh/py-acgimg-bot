"""Deterministic Web admin credentials and login helpers for tests."""

from __future__ import annotations

import os

TEST_ADMIN_USERNAME = "test-admin"
TEST_ADMIN_PASSWORD = "test-password-123"

LOGIN_PATH = "/api/auth/login"


def configure_test_admin() -> None:
    """Force known credentials before the application config is imported."""

    os.environ["ADMIN_USERNAME"] = TEST_ADMIN_USERNAME
    os.environ["ADMIN_PASSWORD"] = TEST_ADMIN_PASSWORD
    os.environ.pop("ADMIN_COOKIE_SECURE", None)


def login_test_admin(client):
    """Log a synchronous HTTP client in and return the login response."""

    from services import admin_auth

    admin_auth.reset_login_rate_limits()
    response = client.post(
        LOGIN_PATH,
        json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response


async def login_test_admin_async(client):
    """Log an asynchronous HTTP client in and return the login response."""

    from services import admin_auth

    admin_auth.reset_login_rate_limits()
    response = await client.post(
        LOGIN_PATH,
        json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response

"""Authentication contracts for the administrative Web API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from auth_helpers import LOGIN_PATH, TEST_ADMIN_PASSWORD, TEST_ADMIN_USERNAME


@pytest.fixture()
def anonymous_client():
    import main
    from services import admin_auth

    admin_auth.reset_login_rate_limits()
    with TestClient(main.app) as client:
        yield client
    admin_auth.reset_login_rate_limits()


PROTECTED_ENDPOINTS = [
    "/api/dashboard/summary",
    "/api/groups",
    "/api/private/users",
    "/api/config/features",
    "/api/bot-tokens",
    "/api/pixiv-tokens",
    "/api/illustrations",
    "/api/illustrations/tasks",
]


@pytest.mark.parametrize("endpoint", PROTECTED_ENDPOINTS)
def test_admin_api_requires_login(anonymous_client, endpoint):
    response = anonymous_client.get(endpoint)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.json()["error"]["message"] == "请先登录管理端"


def test_login_me_and_logout_flow(anonymous_client):
    me = anonymous_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json() == {"authenticated": False, "username": None}

    failed = anonymous_client.post(
        LOGIN_PATH,
        json={"username": TEST_ADMIN_USERNAME, "password": "wrong-password"},
    )
    assert failed.status_code == 401
    assert failed.json()["error"]["code"] == "unauthorized"

    logged_in = anonymous_client.post(
        LOGIN_PATH,
        json={"username": TEST_ADMIN_USERNAME, "password": TEST_ADMIN_PASSWORD},
    )
    assert logged_in.status_code == 200
    assert logged_in.json() == {"authenticated": True, "username": TEST_ADMIN_USERNAME}
    cookie = logged_in.headers["set-cookie"]
    assert "acgimg_admin_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie

    me = anonymous_client.get("/api/auth/me")
    assert me.json() == {"authenticated": True, "username": TEST_ADMIN_USERNAME}
    assert anonymous_client.get("/api/dashboard/summary").status_code == 200

    logged_out = anonymous_client.post("/api/auth/logout")
    assert logged_out.status_code == 200
    assert logged_out.json()["authenticated"] is False
    assert anonymous_client.get("/api/dashboard/summary").status_code == 401


@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
def test_api_documentation_requires_login(anonymous_client, path):
    response = anonymous_client.get(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_api_documentation_is_available_after_login(anonymous_client):
    from auth_helpers import login_test_admin

    login_test_admin(anonymous_client)

    assert anonymous_client.get("/openapi.json").status_code == 200
    assert anonymous_client.get("/docs").status_code == 200


def test_unused_demo_endpoint_is_removed(anonymous_client):
    assert anonymous_client.get("/hello/User").status_code == 404


def test_built_admin_spa_requires_login(anonymous_client):
    import main
    from auth_helpers import login_test_admin

    if not main.dist_dir.exists():
        pytest.skip("production frontend build is not present")

    root = anonymous_client.get("/admin/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "/admin/login"

    deep_link = anonymous_client.get("/admin/dashboard", follow_redirects=False)
    assert deep_link.status_code == 307
    assert deep_link.headers["location"] == "/admin/login?redirect=%2Fdashboard"

    assert anonymous_client.get("/admin/login", follow_redirects=False).status_code == 200

    login_test_admin(anonymous_client)
    assert anonymous_client.get("/admin/", follow_redirects=False).status_code == 200


def test_login_rejects_unknown_username(anonymous_client):
    response = anonymous_client.post(
        LOGIN_PATH,
        json={"username": "someone-else", "password": TEST_ADMIN_PASSWORD},
    )

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "用户名或密码错误"


def test_failed_logins_are_rate_limited(anonymous_client):
    payload = {"username": TEST_ADMIN_USERNAME, "password": "wrong-password"}
    for _ in range(5):
        assert anonymous_client.post(LOGIN_PATH, json=payload).status_code == 401

    blocked = anonymous_client.post(LOGIN_PATH, json=payload)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) > 0


def test_password_change_is_rejected_for_environment_managed_credentials(anonymous_client):
    from auth_helpers import login_test_admin

    login_test_admin(anonymous_client)
    response = anonymous_client.post(
        "/api/auth/password",
        json={
            "current_password": TEST_ADMIN_PASSWORD,
            "new_password": "a-new-password-123",
        },
    )

    assert response.status_code == 409
    assert "ADMIN_PASSWORD" in response.json()["error"]["message"]

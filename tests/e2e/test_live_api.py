"""End-to-end tests: run the real backend (uvicorn) and call the HTTP API.

Unlike ``tests/system`` (TestClient over ASGI), these tests start an actual
uvicorn subprocess against an isolated SQLite database and talk to it over
TCP with httpx.
"""

import uuid


def test_health(live_server_url, http_client):
    response = http_client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello World"}


def test_feature_flags(live_server_url, http_client):
    response = http_client.get("/api/config/features")
    assert response.status_code == 200
    data = response.json()
    keys = {item["key"] for item in data["features"]}
    assert {"allow_r18g", "enable_on_new_group", "pixiv_cache_to_telegram"}.issubset(keys)

    # 开关写入并读回（真实持久化到临时 SQLite）
    response = http_client.put("/api/config/features/allow_r18g", json={"value": True})
    assert response.status_code == 200
    assert response.json()["value"] is True

    data = http_client.get("/api/config/features").json()
    flag = next(item for item in data["features"] if item["key"] == "allow_r18g")
    assert flag["value"] is True


def test_bot_tokens_flow(live_server_url, http_client):
    unique_token = f"123456789:LIVE_TEST_{uuid.uuid4().hex[:12]}"

    response = http_client.put("/api/bot-tokens", json={"token": unique_token, "enabled": True})
    assert response.status_code == 200
    assert response.json()["configured"] is True

    data = http_client.get("/api/bot-tokens").json()
    assert data["token"] == unique_token

    response = http_client.patch("/api/bot-tokens/status", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    response = http_client.delete("/api/bot-tokens")
    assert response.status_code == 200
    assert http_client.get("/api/bot-tokens").json()["configured"] is False


def test_pixiv_tokens_flow(live_server_url, http_client):
    token_a = f"LIVE_REFRESH_{uuid.uuid4().hex[:10]}"
    token_b = f"LIVE_REFRESH_{uuid.uuid4().hex[:10]}"

    assert http_client.post("/api/pixiv-tokens", json={"token": token_a}).status_code == 200
    assert http_client.post("/api/pixiv-tokens", json={"token": token_b}).status_code == 200

    data = http_client.get("/api/pixiv-tokens").json()
    assert data["total"] >= 2

    response = http_client.patch("/api/pixiv-tokens/enabled", json={"enabled": False})
    assert response.status_code == 200

    response = http_client.delete("/api/pixiv-tokens")
    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_dashboard(live_server_url, http_client):
    response = http_client.get("/api/dashboard/summary")
    assert response.status_code == 200
    data = response.json()
    assert "total_groups" in data
    assert "recent_activity" in data


def test_illustration_import_requires_pixiv(live_server_url, http_client):
    # 真实服务器中 Pixiv 未配置 token → 400
    response = http_client.post("/api/illustrations/import", json={"pixiv_id": 1})
    assert response.status_code == 400


def test_illustration_tasks_endpoint(live_server_url, http_client):
    response = http_client.get("/api/illustrations/tasks")
    assert response.status_code == 200
    assert "items" in response.json()

    assert http_client.get("/api/illustrations/tasks/999999").status_code == 404


def test_proxy_rejects_non_pixiv_domain(live_server_url, http_client):
    response = http_client.get(
        "/api/illustrations/image", params={"url": "https://evil.example.com/x.jpg"}
    )
    assert response.status_code == 400

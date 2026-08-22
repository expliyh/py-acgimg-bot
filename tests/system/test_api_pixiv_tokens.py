"""System tests for the Pixiv token management API."""

TOKEN_A = "REFRESH_TOKEN_AAAA"
TOKEN_B = "REFRESH_TOKEN_BBBB"


def test_initial_list_is_empty(client):
    data = client.get("/api/pixiv-tokens").json()
    assert data["total"] == 0
    assert data["items"] == []


def test_add_multiple_tokens(client):
    response = client.post("/api/pixiv-tokens", json={"token": TOKEN_A, "enabled": True})
    assert response.status_code == 200, response.text
    first = response.json()
    assert first["id"] == 1
    assert first["masked"] == "REFR...AAAA"

    second = client.post("/api/pixiv-tokens", json={"token": TOKEN_B, "enabled": True}).json()
    assert second["id"] == 2

    data = client.get("/api/pixiv-tokens").json()
    assert data["total"] == 2
    assert {item["id"] for item in data["items"]} == {1, 2}


def test_toggle_single_token(client):
    client.post("/api/pixiv-tokens", json={"token": TOKEN_A, "enabled": True})
    response = client.patch("/api/pixiv-tokens/1/status", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_toggle_all_tokens(client):
    client.post("/api/pixiv-tokens", json={"token": TOKEN_A})
    client.post("/api/pixiv-tokens", json={"token": TOKEN_B})
    response = client.patch("/api/pixiv-tokens", json={"enabled": False})
    assert response.status_code == 200, response.text
    assert all(item["enabled"] is False for item in response.json()["items"])


def test_update_token(client):
    client.post("/api/pixiv-tokens", json={"token": TOKEN_A})
    response = client.put("/api/pixiv-tokens/1", json={"token": "REFRESH_TOKEN_UPDATED"})
    assert response.status_code == 200
    assert response.json()["token"] == "REFRESH_TOKEN_UPDATED"


def test_empty_token_rejected(client):
    response = client.post("/api/pixiv-tokens", json={"token": "   "})
    assert response.status_code == 400


def test_update_missing_token_returns_404(client):
    response = client.put("/api/pixiv-tokens/999", json={"token": TOKEN_A})
    assert response.status_code == 404


def test_delete(client):
    client.post("/api/pixiv-tokens", json={"token": TOKEN_A})
    client.post("/api/pixiv-tokens", json={"token": TOKEN_B})

    response = client.delete("/api/pixiv-tokens/1")
    assert response.status_code == 200
    assert client.get("/api/pixiv-tokens").json()["total"] == 1

    response = client.delete("/api/pixiv-tokens")
    assert response.status_code == 200
    assert client.get("/api/pixiv-tokens").json()["total"] == 0

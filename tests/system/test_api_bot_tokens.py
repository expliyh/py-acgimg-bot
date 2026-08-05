"""System tests for the bot token management API."""

TOKEN = "123456789:TEST_TOKEN_abcdefghijklmnop"


def test_initial_state_is_unconfigured(client):
    data = client.get("/api/bot-tokens").json()
    assert data["configured"] is False
    assert data["token"] is None
    assert data["enabled"] is None


def test_set_and_read_back(client):
    response = client.put("/api/bot-tokens", json={"token": TOKEN, "enabled": True})
    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is True
    assert data["token"] == TOKEN
    assert data["masked"] == "1234...mnop"
    assert data["enabled"] is True

    read_back = client.get("/api/bot-tokens").json()
    assert read_back["token"] == TOKEN


def test_toggle_enabled(client):
    client.put("/api/bot-tokens", json={"token": TOKEN, "enabled": True})
    response = client.patch("/api/bot-tokens/status", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False


def test_empty_token_rejected(client):
    response = client.put("/api/bot-tokens", json={"token": "   "})
    assert response.status_code == 400


def test_toggle_without_config_returns_404(client):
    response = client.patch("/api/bot-tokens/status", json={"enabled": False})
    assert response.status_code == 404


def test_delete(client):
    client.put("/api/bot-tokens", json={"token": TOKEN})
    response = client.delete("/api/bot-tokens")
    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert client.get("/api/bot-tokens").json()["configured"] is False

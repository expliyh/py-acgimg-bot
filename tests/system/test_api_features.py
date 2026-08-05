"""System tests for the feature-flag configuration API."""

EXPECTED_FEATURE_KEYS = {"allow_r18g", "enable_on_new_group", "pixiv_cache_to_telegram"}


def test_list_features(client):
    response = client.get("/api/config/features")
    assert response.status_code == 200
    data = response.json()
    keys = {item["key"] for item in data["features"]}
    assert EXPECTED_FEATURE_KEYS.issubset(keys)
    assert all(item["editable"] for item in data["features"])
    # 占位项不可编辑
    assert all(not item["editable"] for item in data["placeholders"])


def test_toggle_feature_flag(client):
    response = client.put("/api/config/features/allow_r18g", json={"value": True})
    assert response.status_code == 200
    assert response.json()["value"] is True

    # 读回（持久化）
    data = client.get("/api/config/features").json()
    flag = next(item for item in data["features"] if item["key"] == "allow_r18g")
    assert flag["value"] is True


def test_toggle_unknown_feature_returns_404(client):
    response = client.put("/api/config/features/does_not_exist", json={"value": True})
    assert response.status_code == 404

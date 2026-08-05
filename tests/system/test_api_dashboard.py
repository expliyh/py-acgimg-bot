"""System tests for the dashboard API."""


def test_dashboard_summary_empty_database(client):
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total_groups"] == 0
    assert data["active_groups"] == 0
    assert data["total_users"] == 0
    assert data["total_group_messages"] == 0
    assert data["total_private_messages"] == 0
    assert data["recent_activity"] == []

"""Tests for the admin API pagination contract."""


def test_group_list_uses_page_contract(client):
    response = client.get(
        "/api/groups",
        params={"page": 1, "page_size": 10, "sort_by": "id", "sort_order": "desc"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 10,
        "pages": 0,
    }


def test_command_history_rejects_unknown_sort_field(client):
    response = client.get("/api/commands/history", params={"sort_by": "not_a_field"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_import_tasks_exposes_page_contract(client):
    response = client.get("/api/illustrations/tasks", params={"page": 1, "page_size": 10})

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 10,
        "pages": 0,
    }

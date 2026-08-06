from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from utils.admin_static import AdminStaticFiles


def test_admin_static_files_support_spa_history_routes(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>Admin console</h1>", encoding="utf-8")
    (tmp_path / "app.js").write_text("console.log('admin')", encoding="utf-8")
    app = FastAPI()
    app.mount("/admin", AdminStaticFiles(directory=tmp_path, html=True))

    with TestClient(app) as client:
        index_response = client.get("/admin/")
        route_response = client.get("/admin/groups")
        asset_response = client.get("/admin/app.js")

    assert index_response.status_code == 200
    assert index_response.text == "<h1>Admin console</h1>"
    assert route_response.status_code == 200
    assert route_response.text == index_response.text
    assert asset_response.status_code == 200
    assert asset_response.text == "console.log('admin')"

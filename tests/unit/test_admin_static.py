from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from utils.admin_static import AdminStaticFiles, redirect_to_admin


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


def test_root_redirects_to_built_in_admin_webui(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>Admin console</h1>", encoding="utf-8")
    app = FastAPI()
    app.mount("/admin", AdminStaticFiles(directory=tmp_path, html=True))
    app.add_api_route("/", redirect_to_admin)

    with TestClient(app, follow_redirects=False) as client:
        response = client.get("/")

    assert response.status_code == 307
    assert response.headers["location"] == "/admin/"

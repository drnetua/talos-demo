from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notes.app import UI_ASSETS, create_app
from notes.db import Database


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Database(":memory:")))


def test_page_is_html_and_links_assets(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-cache"
    assert "/ui/app.css" in r.text
    assert "/ui/app.js" in r.text


@pytest.mark.parametrize(("name", "ctype"), list(UI_ASSETS.items()))
def test_assets(client: TestClient, name: str, ctype: str) -> None:
    r = client.get(f"/ui/{name}")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(ctype)
    assert r.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/ui/unknown", "/ui/..%2Fapp.py", "/ui/sub/app.js"])
def test_unknown_assets_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_ui_routes_not_in_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/" not in paths
    assert not any(p.startswith("/ui") for p in paths)
    assert "/notes" in paths
    assert "/notes/{note_id}" in paths


def test_app_js_uses_api_without_inner_html() -> None:
    js = (Path(__file__).parent.parent / "src/notes/ui/app.js").read_text()
    assert "/notes" in js
    assert "innerHTML" not in js

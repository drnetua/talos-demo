from fastapi.testclient import TestClient

from notes.app import create_app
from notes.db import Database


def client() -> TestClient:
    return TestClient(create_app(Database(":memory:")))


def test_crud_and_tags() -> None:
    c = client()
    assert c.get("/health").json() == {"status": "ok"}
    note = c.post(
        "/notes", json={"title": "Buy milk", "body": "2L", "tags": ["Home", "shop"]}
    ).json()
    assert note["tags"] == ["home", "shop"]
    assert c.get(f"/notes/{note['id']}").json()["title"] == "Buy milk"
    updated = c.put(f"/notes/{note['id']}", json={"title": "Buy oat milk", "tags": ["home"]}).json()
    assert updated["title"] == "Buy oat milk" and updated["tags"] == ["home"]
    assert c.post(f"/notes/{note['id']}/tags/urgent").json()["tags"] == ["home", "urgent"]
    assert c.delete(f"/notes/{note['id']}/tags/home").json()["tags"] == ["urgent"]
    assert c.get("/tags").json() == [{"tag": "urgent", "count": 1}]
    assert [n["id"] for n in c.get("/notes?tag=urgent").json()] == [note["id"]]
    assert c.delete(f"/notes/{note['id']}").status_code == 204
    assert c.get(f"/notes/{note['id']}").status_code == 404


def test_search_and_list() -> None:
    c = client()
    c.post("/notes", json={"title": "Alpha", "body": "first"})
    c.post("/notes", json={"title": "Beta", "body": "second alpha"})
    assert [n["title"] for n in c.get("/notes/search?q=alpha").json()] == ["Alpha", "Beta"]
    assert len(c.get("/notes").json()) == 2
    assert c.get("/notes/search?q=").status_code == 422
    assert c.put("/notes/99", json={"title": "x"}).status_code == 404

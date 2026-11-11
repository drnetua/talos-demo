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
    assert [n["id"] for n in c.get("/notes?tag=urgent").json()["items"]] == [note["id"]]
    assert c.delete(f"/notes/{note['id']}").status_code == 204
    assert c.get(f"/notes/{note['id']}").status_code == 404


def test_search_and_list() -> None:
    c = client()
    c.post("/notes", json={"title": "Alpha", "body": "first"})
    c.post("/notes", json={"title": "Beta", "body": "second alpha"})
    assert [n["title"] for n in c.get("/notes/search?q=alpha").json()] == ["Alpha", "Beta"]
    assert len(c.get("/notes").json()["items"]) == 2
    assert c.get("/notes/search?q=").status_code == 422
    assert c.put("/notes/99", json={"title": "x"}).status_code == 404


def _seed(c: TestClient, n: int, tags: list[str] | None = None) -> None:
    for i in range(n):
        c.post("/notes", json={"title": f"n{i}", "tags": tags or []})


def test_default_page_is_bounded() -> None:
    c = client()
    _seed(c, 120)
    r = c.get("/notes")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 50
    assert r.json()["next_cursor"] is None


def test_limit_page() -> None:
    c = client()
    _seed(c, 120)
    assert len(c.get("/notes?limit=5").json()["items"]) == 5
    assert len(c.get("/notes?limit=100").json()["items"]) == 100


def test_limit_over_max_rejected() -> None:
    c = client()
    _seed(c, 120)
    r = c.get("/notes?limit=101")
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["query", "limit"]
    assert "items" not in r.json()


def test_empty_page() -> None:
    c = client()
    assert c.get("/notes").json() == {"items": [], "next_cursor": None}


def test_tag_page_bounded_and_ordered() -> None:
    c = client()
    _seed(c, 3, ["Work"])
    _seed(c, 2)
    items = c.get("/notes?tag=WORK&limit=2").json()["items"]
    assert [n["id"] for n in items] == [1, 2]


def test_openapi_list_notes() -> None:
    c = client()
    op = c.get("/openapi.json").json()["paths"]["/notes"]["get"]
    assert op["operationId"] == "list-notes"
    limit = next(p for p in op["parameters"] if p["name"] == "limit")["schema"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 100, 50)
    assert op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/NotesPage"
    )

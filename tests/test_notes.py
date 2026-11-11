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
    assert r.json()["next_cursor"] is not None


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


def _ids(r: object) -> list[int]:
    return [n["id"] for n in r.json()["items"]]  # type: ignore[attr-defined]


def _walk(c: TestClient, query: str) -> list[int]:
    ids: list[int] = []
    url = f"/notes?{query}"
    for _ in range(100):
        body = c.get(url).json()
        ids += [n["id"] for n in body["items"]]
        if body["next_cursor"] is None:
            return ids
        url = f"/notes?{query}&cursor={body['next_cursor']}"
    raise AssertionError("walk did not end")


def test_cursor_continues_after_last_id() -> None:
    c = client()
    _seed(c, 5)
    first = c.get("/notes?limit=2")
    assert len(_ids(first)) == 2 and first.json()["next_cursor"]
    second = c.get(f"/notes?limit=2&cursor={first.json()['next_cursor']}")
    assert _ids(second) == [3, 4]
    last = c.get(f"/notes?limit=2&cursor={second.json()['next_cursor']}")
    assert _ids(last) == [5] and last.json()["next_cursor"] is None


def test_exact_fill_has_no_cursor() -> None:
    c = client()
    _seed(c, 4)
    assert c.get("/notes?limit=4").json()["next_cursor"] is None


def test_full_walk_every_id_once_and_repeatable() -> None:
    c = client()
    _seed(c, 11)
    walk = _walk(c, "limit=3")
    assert walk == list(range(1, 12))
    assert _walk(c, "limit=3") == walk
    assert _walk(c, "limit=4") == walk


def test_full_walk_with_tag() -> None:
    c = client()
    for i in range(9):
        c.post("/notes", json={"title": f"n{i}", "tags": ["Work"] if i % 2 == 0 else []})
    assert _walk(c, "tag=WORK&limit=2") == [1, 3, 5, 7, 9]


def test_bad_cursor_is_422() -> None:
    c = client()
    _seed(c, 5)
    good = c.get("/notes?limit=2").json()["next_cursor"]
    payload, sig = good.split(".")
    for bad in ("garbage", "a.b", f"{payload}.{sig[:-2]}xx", f"{payload}x.{sig}", ".", "x."):
        r = c.get("/notes", params={"cursor": bad})
        assert r.status_code == 422 and r.json() == {"detail": "invalid page cursor"}

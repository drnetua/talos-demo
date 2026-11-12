import base64

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
    for bad in (
        "",
        "garbage",
        "é.é",
        "a.b",
        payload,
        f"{payload}.",
        f"{payload}.{sig[:5]}",
        "a.b",
        f"{payload}.{sig[:-2]}xx",
        f"{payload}x.{sig}",
        ".",
        "x.",
    ):
        r = c.get("/notes", params={"cursor": bad})
        assert r.status_code == 422 and r.json() == {"detail": "invalid page cursor"}


def test_invalid_limit_is_422_without_items() -> None:
    c = client()
    _seed(c, 3)
    for bad in ("0", "-1", "-5", "abc", "1.5"):
        r = c.get("/notes", params={"limit": bad})
        assert r.status_code == 422
        assert r.json()["detail"][0]["loc"] == ["query", "limit"]
        assert "items" not in r.json()


def test_tampered_payload_cursor_is_422() -> None:
    c = client()
    _seed(c, 5)
    payload, sig = c.get("/notes?limit=2").json()["next_cursor"].split(".")
    forged = base64.urlsafe_b64encode(b'{"a":0,"t":null}').decode().rstrip("=")
    r = c.get("/notes", params={"cursor": f"{forged}.{sig}"})
    assert r.status_code == 422 and r.json() == {"detail": "invalid page cursor"}
    assert "items" not in r.json()


def test_openapi_cursor_min_length_and_422() -> None:
    op = client().get("/openapi.json").json()["paths"]["/notes"]["get"]
    cursor = next(p for p in op["parameters"] if p["name"] == "cursor")["schema"]
    assert any(v.get("minLength") == 1 for v in cursor.get("anyOf", [cursor]))
    assert "422" in op["responses"]


def _tag_client() -> TestClient:
    c = client()
    for i in range(7):
        c.post("/notes", json={"title": f"n{i}", "tags": ["work"] if i % 2 == 0 else ["home"]})
    return c


def test_tag_page_has_cursor_and_only_tag_notes() -> None:
    c = _tag_client()
    r = c.get("/notes?tag=work&limit=2")
    assert _ids(r) == [1, 3] and r.json()["next_cursor"]
    assert all("work" in n["tags"] for n in r.json()["items"])


def test_tag_walk_any_case_returns_each_once() -> None:
    c = _tag_client()
    assert _walk(c, "tag=work&limit=2") == [1, 3, 5, 7]
    assert _walk(c, "tag=WORK&limit=3") == [1, 3, 5, 7]
    cursor = c.get("/notes?tag=work&limit=2").json()["next_cursor"]
    assert _ids(c.get(f"/notes?tag=WORK&limit=2&cursor={cursor}")) == [5, 7]


def test_cursor_with_other_tag_or_no_tag_is_422() -> None:
    c = _tag_client()
    cursor = c.get("/notes?tag=work&limit=2").json()["next_cursor"]
    for query in ("tag=home", ""):
        r = c.get(f"/notes?{query}&cursor={cursor}")
        assert r.status_code == 422
        assert r.json() == {"detail": "page cursor does not match the tag filter"}


def test_no_tag_cursor_with_tag_is_422_and_empty_tag_is_no_filter() -> None:
    c = _tag_client()
    cursor = c.get("/notes?limit=2").json()["next_cursor"]
    r = c.get(f"/notes?tag=work&cursor={cursor}")
    assert r.status_code == 422
    assert r.json() == {"detail": "page cursor does not match the tag filter"}
    assert c.get(f"/notes?tag=&cursor={cursor}").status_code == 200


NOTE_FIELDS = {"id", "title", "body", "tags", "created_at", "updated_at"}


def _seed_matching(c: TestClient, n: int) -> None:
    for i in range(n):
        c.post("/notes", json={"title": f"n{i}", "body": "findme"})


def test_search_unpaginated() -> None:
    c = client()
    _seed_matching(c, 60)
    c.post("/notes", json={"title": "other", "body": "nothing"})
    r = c.get("/notes/search?q=findme")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    ids = [n["id"] for n in body]
    assert ids == list(range(1, 61))
    assert all(set(n) == NOTE_FIELDS for n in body)


def test_search_ignores_paging_parameters() -> None:
    c = client()
    _seed_matching(c, 60)
    r = c.get("/notes/search?q=findme&limit=1&cursor=x")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert [n["id"] for n in r.json()] == list(range(1, 61))


def test_tags_unpaginated() -> None:
    c = client()
    for i in range(60):
        tags = [f"t{i:02d}"] + (["shared"] if i % 2 == 0 else [])
        c.post("/notes", json={"title": f"n{i}", "tags": tags})
    r = c.get("/tags")
    assert r.status_code == 200
    expected = [{"tag": f"t{i:02d}", "count": 1} for i in range(60)]
    expected.append({"tag": "shared", "count": 30})
    assert r.json() == sorted(expected, key=lambda t: str(t["tag"]))
    assert isinstance(r.json(), list)

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notes.app import create_app
from notes.db import Database


@pytest.fixture(params=["memory", "file"])
def db(request: pytest.FixtureRequest, tmp_path: Path) -> Database:
    return Database() if request.param == "memory" else Database(tmp_path / "n.sqlite3")


def test_parallel_requests_never_fail(db: Database) -> None:
    client = TestClient(create_app(db))
    ids = [client.post("/notes", json={"title": f"n{i}"}).json()["id"] for i in range(6)]

    def work(i: int) -> list[int]:
        nid = ids[i % len(ids)]
        return [
            client.post("/notes", json={"title": "x", "tags": ["a"]}).status_code,
            client.put(f"/notes/{nid}", json={"title": "y", "tags": ["b"]}).status_code,
            client.post(f"/notes/{nid}/tags/t{i}").status_code,
            client.delete(f"/notes/{nid}/tags/t{i}").status_code,
            client.get("/notes").status_code,
            client.get("/notes/export", params={"fields": "id"}).status_code,
            client.delete(f"/notes/{nid}").status_code,
        ]

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = [s for r in pool.map(work, range(24)) for s in r]
    assert all(s in (200, 201, 204, 404) for s in results), set(results)
    assert client.get("/health").status_code == 200


def test_racing_delete_gives_404(db: Database) -> None:
    client = TestClient(create_app(db))
    nid = client.post("/notes", json={"title": "n"}).json()["id"]
    calls = [
        lambda: client.delete(f"/notes/{nid}").status_code,
        lambda: client.put(f"/notes/{nid}", json={"title": "z"}).status_code,
        lambda: client.post(f"/notes/{nid}/tags/q").status_code,
        lambda: client.delete(f"/notes/{nid}/tags/q").status_code,
        lambda: client.delete(f"/notes/{nid}").status_code,
    ] * 4
    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = [f.result() for f in [pool.submit(c) for c in calls]]
    assert all(c in (200, 201, 204, 404) for c in codes), codes


def test_session_nested_and_exception_release(db: Database) -> None:
    with db.session(), db.session(), db.tx():
        pass
    with pytest.raises(RuntimeError), db.session():
        raise RuntimeError("boom")
    client = TestClient(create_app(db))
    assert client.get("/notes/999").status_code == 404
    assert client.post("/notes", json={"title": "ok"}).status_code == 201

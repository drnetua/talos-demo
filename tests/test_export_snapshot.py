import csv
import io
import json
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import notes.app as app_module
from notes.app import create_app
from notes.db import Database

ALL = ["id", "title", "body", "tags", "created_at", "updated_at"]


@pytest.fixture(params=["memory", "file"])
def db(request: pytest.FixtureRequest, tmp_path: Path) -> Database:
    return Database() if request.param == "memory" else Database(tmp_path / "n.sqlite3")


def parse(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def pause_after_first_read(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[threading.Event, threading.Event]:
    reached, resume = threading.Event(), threading.Event()
    original = Database._read_tags

    def paused(conn: sqlite3.Connection, tag: str | None) -> dict[int, list[str]]:
        reached.set()
        assert resume.wait(10)
        return original(conn, tag)

    monkeypatch.setattr(Database, "_read_tags", staticmethod(paused))
    return reached, resume


def export_paused(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    mutate: Callable[[], None],
    **params: Any,
) -> list[dict[str, str]]:
    reached, resume = pause_after_first_read(monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(client.get, "/notes/export", params={"fields": ALL, **params})
        assert reached.wait(10)
        # session ownership is held by the capture: mutations wait, so run them async
        mutator = pool.submit(mutate)
        resume.set()
        response = future.result(10)
        mutator.result(10)
    assert response.status_code == 200
    return parse(response.text)


def test_edit_during_capture_does_not_mix_versions(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(create_app(db))
    client.post("/notes", json={"title": "old", "body": "old body", "tags": ["a"]})
    reference = parse(client.get("/notes/export", params={"fields": ALL}).text)
    rows = export_paused(
        client,
        monkeypatch,
        lambda: client.put("/notes/1", json={"title": "new", "body": "new", "tags": ["z"]}),
    )
    assert rows == reference
    assert client.get("/notes/1").json()["title"] == "new"


def test_create_and_delete_during_capture(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(create_app(db))
    for i in range(3):
        client.post("/notes", json={"title": f"n{i}"})
    reference = parse(client.get("/notes/export", params={"fields": ALL}).text)

    def mutate() -> None:
        client.post("/notes", json={"title": "late"})
        client.delete("/notes/2")

    rows = export_paused(client, monkeypatch, mutate)
    assert rows == reference
    assert [r["id"] for r in rows] == ["1", "2", "3"]


def test_tag_filter_snapshot(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(create_app(db))
    client.post("/notes", json={"title": "a", "tags": ["x", "y"]})
    client.post("/notes", json={"title": "b", "tags": ["y"]})
    rows = export_paused(client, monkeypatch, lambda: client.post("/notes/2/tags/x"), tag="X")
    assert [(r["id"], json.loads(r["tags"])) for r in rows] == [("1", ["x", "y"])]


def test_mutation_after_capture_does_not_change_file(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = TestClient(create_app(db))
    client.post("/notes", json={"title": "before"})
    real = app_module.capture_notes

    def capture_then_mutate(database: Database, tag: str | None) -> list[dict[str, Any]]:
        notes = real(database, tag)
        client.put("/notes/1", json={"title": "after"})
        client.post("/notes", json={"title": "extra"})
        return notes

    monkeypatch.setattr(app_module, "capture_notes", capture_then_mutate)
    rows = parse(client.get("/notes/export", params={"fields": ["id", "title"]}).text)
    assert rows == [{"id": "1", "title": "before"}]
    assert not db.conn.in_transaction


def test_capture_releases_transaction(db: Database) -> None:
    db.snapshot()
    assert not db.conn.in_transaction
    assert db._lock.acquire(blocking=False)
    db._lock.release()


def test_racing_requests_never_fail(db: Database) -> None:
    client = TestClient(create_app(db))
    ids = [client.post("/notes", json={"title": f"n{i}"}).json()["id"] for i in range(4)]

    def work(i: int) -> list[int]:
        nid = ids[i % len(ids)]
        return [
            client.get("/notes/export", params={"fields": ALL}).status_code,
            client.post("/notes", json={"title": "c", "tags": ["t"]}).status_code,
            client.put(f"/notes/{nid}", json={"title": "e", "tags": ["u"]}).status_code,
            client.post(f"/notes/{nid}/tags/q{i}").status_code,
            client.delete(f"/notes/{nid}").status_code,
            client.get("/notes/export", params={"fields": "id", "tag": "t"}).status_code,
        ]

    with ThreadPoolExecutor(max_workers=12) as pool:
        statuses = [s for r in pool.map(work, range(20)) for s in r]
    assert all(s in (200, 201, 204, 404) for s in statuses), set(statuses)


def test_150_exports_have_no_mixed_rows(db: Database) -> None:
    client = TestClient(create_app(db))
    for _ in range(5):
        client.post("/notes", json={"title": "v0", "body": "v0", "tags": ["v0"]})
    stop = threading.Event()

    def writer() -> None:
        n = 1
        while not stop.is_set():
            version = f"v{n}"
            for nid in range(1, 6):
                client.put(
                    f"/notes/{nid}", json={"title": version, "body": version, "tags": [version]}
                )
            created = client.post("/notes", json={"title": "tmp", "body": "tmp", "tags": ["tmp"]})
            client.delete(f"/notes/{created.json()['id']}")
            n += 1

    def export(_: int) -> tuple[int, str]:
        response = client.get("/notes/export", params={"fields": ALL})
        return response.status_code, response.text

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(export, range(150)))
    finally:
        stop.set()
        thread.join()
    assert all(status == 200 for status, _ in results)
    for _, text in results:
        for row in parse(text):
            tags = json.loads(row["tags"])
            assert len(tags) == 1 and row["title"] == row["body"] == tags[0], row


@pytest.mark.parametrize("target", ["capture", "serialization", "db"])
def test_failure_returns_safe_500(
    db: Database, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    client = TestClient(create_app(db))
    client.post("/notes", json={"title": "secret text"})

    def boom(*_: Any, **__: Any) -> Any:
        raise RuntimeError("secret text")

    if target == "capture":
        monkeypatch.setattr(app_module, "capture_notes", boom)
    elif target == "serialization":
        monkeypatch.setattr(csv, "writer", boom)
    else:
        monkeypatch.setattr(Database, "_read_tags", staticmethod(boom))
    response = client.get("/notes/export", params={"fields": ALL})
    assert response.status_code == 500
    assert response.json() == {"detail": "Export could not be completed"}
    assert "Content-Disposition" not in response.headers
    assert "secret" not in response.text
    monkeypatch.undo()
    assert not db.conn.in_transaction
    again = client.get("/notes/export", params={"fields": "title"})
    assert again.text == "title\r\nsecret text\r\n"
    assert client.post("/notes", json={"title": "ok"}).status_code == 201

"""Regression tests: the JSON API and its generated docs stay as before the UI."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from notes.app import create_app
from notes.db import Database

BASELINE = Path(__file__).parent / "fixtures" / "openapi_baseline.json"
NOTE_FIELDS = {"id", "title", "body", "tags", "created_at", "updated_at"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Database(":memory:")))


def test_openapi_equals_baseline(client: TestClient) -> None:
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert r.json() == json.loads(BASELINE.read_text())
    paths = r.json()["paths"]
    assert "/" not in paths
    assert not any(p.startswith("/ui") for p in paths)


def test_docs_served(client: TestClient) -> None:
    r = client.get("/docs")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


def test_operation_walk(client: TestClient) -> None:
    # Plain requests: no Origin and no Sec-Fetch-Site, as curl sends them.
    r = client.post("/notes", json={"title": "Buy milk", "body": "2L", "tags": ["Home"]})
    assert r.status_code == 201
    note = r.json()
    assert set(note) == NOTE_FIELDS
    assert note["tags"] == ["home"]
    nid = note["id"]

    r = client.get(f"/notes/{nid}")
    assert r.status_code == 200
    assert set(r.json()) == NOTE_FIELDS

    r = client.put(f"/notes/{nid}", json={"title": "Buy oat milk", "tags": ["home"]})
    assert r.status_code == 200
    assert set(r.json()) == NOTE_FIELDS
    assert r.json()["title"] == "Buy oat milk"

    r = client.get("/notes/search", params={"q": "oat"})
    assert r.status_code == 200
    assert [n["id"] for n in r.json()] == [nid]
    assert set(r.json()[0]) == NOTE_FIELDS

    r = client.get("/notes")
    assert r.status_code == 200
    assert set(r.json()) == {"items", "next_cursor"}
    assert [n["id"] for n in r.json()["items"]] == [nid]
    assert r.json()["next_cursor"] is None

    r = client.get("/tags")
    assert r.status_code == 200
    assert r.json() == [{"tag": "home", "count": 1}]

    r = client.post(f"/notes/{nid}/tags/urgent")
    assert r.status_code == 201
    assert set(r.json()) == NOTE_FIELDS
    assert r.json()["tags"] == ["home", "urgent"]

    r = client.delete(f"/notes/{nid}/tags/home")
    assert r.status_code == 200
    assert set(r.json()) == NOTE_FIELDS
    assert r.json()["tags"] == ["urgent"]

    r = client.delete(f"/notes/{nid}")
    assert r.status_code == 204
    assert r.content == b""

    assert client.get(f"/notes/{nid}").status_code == 404

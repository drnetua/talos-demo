"""Cross-site browser writes are rejected with 403; everything else is unchanged."""

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from notes.app import create_app
from notes.db import Database

BASELINE = Path(__file__).parent / "fixtures" / "openapi_baseline.json"
REJECTED = {"detail": "cross-site request rejected"}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Database(":memory:")))


@pytest.fixture
def note_id(client: TestClient) -> int:
    r = client.post("/notes", json={"title": "Keep", "body": "me", "tags": ["a"]})
    return int(r.json()["id"])


def unsafe_calls(note_id: int) -> list[tuple[str, str, dict[str, Any]]]:
    body = {"json": {"title": "Changed", "body": "x", "tags": ["z"]}}
    return [
        ("POST", "/notes", body),
        ("PUT", f"/notes/{note_id}", body),
        ("DELETE", f"/notes/{note_id}", {}),
        ("POST", f"/notes/{note_id}/tags/new", {}),
        ("DELETE", f"/notes/{note_id}/tags/a", {}),
    ]


def test_cross_site_fetch_metadata_rejected(client: TestClient, note_id: int) -> None:
    before = client.get(f"/notes/{note_id}").json()
    for method, path, kwargs in unsafe_calls(note_id):
        r = client.request(method, path, headers={"Sec-Fetch-Site": "cross-site"}, **kwargs)
        assert r.status_code == 403, (method, path)
        assert r.json() == REJECTED
    assert client.get(f"/notes/{note_id}").json() == before
    assert len(client.get("/notes").json()["items"]) == 1


@pytest.mark.parametrize("origin", ["https://evil.example", "null"])
def test_foreign_origin_without_fetch_metadata_rejected(
    client: TestClient, note_id: int, origin: str
) -> None:
    before = client.get(f"/notes/{note_id}").json()
    for method, path, kwargs in unsafe_calls(note_id):
        r = client.request(method, path, headers={"Origin": origin}, **kwargs)
        assert r.status_code == 403, (method, path)
        assert r.json() == REJECTED
    assert client.get(f"/notes/{note_id}").json() == before


@pytest.mark.parametrize("origin", ["http://testserver", "http://testserver:80"])
def test_own_origin_passes(client: TestClient, origin: str) -> None:
    r = client.post("/notes", json={"title": "Own"}, headers={"Origin": origin})
    assert r.status_code == 201


@pytest.mark.parametrize("site", ["same-origin", "same-site", "none"])
def test_non_cross_site_fetch_metadata_passes(client: TestClient, site: str) -> None:
    r = client.post("/notes", json={"title": "Ok"}, headers={"Sec-Fetch-Site": site})
    assert r.status_code == 201
    note_id = r.json()["id"]
    h = {"Sec-Fetch-Site": site}
    assert client.put(f"/notes/{note_id}", json={"title": "N"}, headers=h).status_code == 200
    assert client.post(f"/notes/{note_id}/tags/t", headers=h).status_code == 201
    assert client.delete(f"/notes/{note_id}/tags/t", headers=h).status_code == 200
    assert client.delete(f"/notes/{note_id}", headers=h).status_code == 204


def test_fetch_metadata_wins_over_origin(client: TestClient) -> None:
    h = {"Sec-Fetch-Site": "same-origin", "Origin": "https://evil.example"}
    assert client.post("/notes", json={"title": "x"}, headers=h).status_code == 201


def test_no_headers_pass_as_before(client: TestClient, note_id: int) -> None:
    assert client.post("/notes", json={"title": "Plain"}).status_code == 201
    assert client.delete(f"/notes/{note_id}").status_code == 204


def test_reads_not_rejected(client: TestClient) -> None:
    h = {"Sec-Fetch-Site": "cross-site"}
    for path in ("/notes", "/tags", "/"):
        assert client.get(path, headers=h).status_code == 200, path


def test_forwarded_headers_ignored(client: TestClient) -> None:
    fwd = {"X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "https"}
    foreign = {"Origin": "https://evil.example", **fwd}
    assert client.post("/notes", json={"title": "x"}, headers=foreign).status_code == 403
    own = {"Origin": "http://testserver", **fwd}
    assert client.post("/notes", json={"title": "x"}, headers=own).status_code == 201


def test_openapi_unchanged(client: TestClient) -> None:
    assert client.get("/openapi.json").json() == json.loads(BASELINE.read_text())

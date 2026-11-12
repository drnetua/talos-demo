"""Acceptance contract of the CSV export: QA runs it on feature-acceptance, not the regular checks.

uv run pytest acceptance --no-cov
"""

import csv
import io

from fastapi.testclient import TestClient

from notes.app import create_app
from notes.db import Database

HEADER = ["id", "title", "body", "tags", "created_at", "updated_at"]


def _client() -> TestClient:
    return TestClient(create_app(Database(":memory:")))


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_export_all_notes() -> None:
    client = _client()
    client.post(
        "/notes",
        json={"title": "Groceries, weekly", "body": 'milk\n"oat"', "tags": ["home", "Food"]},
    )
    client.post("/notes", json={"title": "Plain", "body": "", "tags": []})
    r = client.get("/notes/export.csv")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == 'attachment; filename="notes.csv"'
    rows = _rows(r.text)
    assert rows[0] == HEADER
    assert rows[1][:4] == ["1", "Groceries, weekly", 'milk\n"oat"', "food|home"]
    assert rows[2][:4] == ["2", "Plain", "", ""]
    assert r.text.endswith("\r\n")


def test_export_by_tag() -> None:
    client = _client()
    client.post("/notes", json={"title": "A", "tags": ["work"]})
    client.post("/notes", json={"title": "B", "tags": ["home"]})
    r = client.get("/notes/export.csv", params={"tag": "Work"})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="notes-work.csv"'
    rows = _rows(r.text)
    assert [row[1] for row in rows[1:]] == ["A"]


def test_export_empty() -> None:
    r = _client().get("/notes/export.csv")
    assert r.status_code == 200
    assert _rows(r.text) == [HEADER]

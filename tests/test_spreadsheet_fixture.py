import csv
from pathlib import Path

from fastapi.testclient import TestClient
from spreadsheet_fixture import FIXTURE_NOTES, ORDINARY_NOTES, write_fixture_csv

from notes.app import create_app
from notes.db import Database


def parsed(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_fixture_file_has_markers_on_formula_like_cells_only(tmp_path: Path) -> None:
    rows = parsed(write_fixture_csv(tmp_path / "fixture.csv"))
    assert len(rows) == len(FIXTURE_NOTES) + len(ORDINARY_NOTES)
    for row, note in zip(rows, FIXTURE_NOTES, strict=False):
        for field in ("title", "body"):
            assert row[field] == "'" + note[field]
    for row, note in zip(rows[len(FIXTURE_NOTES) :], ORDINARY_NOTES, strict=True):
        assert row["title"] == note["title"]
        assert row["body"] == note["body"]


def test_fixture_covers_required_payloads() -> None:
    titles = [note["title"] for note in FIXTURE_NOTES]
    for required in ("=1+1", "+1+1", "-1+1", "@SUM(1,1)", " =1+1", "\t=1+1", "\r=1+1"):
        assert required in titles
    assert any(t.startswith("=HYPERLINK") for t in titles)
    assert [n["title"] for n in ORDINARY_NOTES] == ["Meeting"]
    assert ORDINARY_NOTES[0]["body"] == "\tindented"


def test_export_leaves_stored_notes_unchanged() -> None:
    client = TestClient(create_app(Database(":memory:")))
    for note in FIXTURE_NOTES:
        client.post("/notes", json=note)
    before = client.get("/notes").json()
    client.get("/notes/export", params={"fields": ["id", "title", "body", "tags"]})
    assert client.get("/notes").json() == before
    assert [n["title"] for n in before] == [n["title"] for n in FIXTURE_NOTES]

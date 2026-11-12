"""Formula-like fixture export for manual spreadsheet verification.

Usage: uv run python tests/spreadsheet_fixture.py <out.csv>
"""

import sys
from pathlib import Path

from fastapi.testclient import TestClient

from notes.app import create_app
from notes.db import Database

HYPERLINK = '=HYPERLINK("https://example.invalid/","harmless")'
PAYLOADS = ("=1+1", "+1+1", "-1+1", "@SUM(1,1)", " =1+1", "\t=1+1", "\r=1+1", HYPERLINK)

# Every title and body is formula-like: the export must mark each one.
FIXTURE_NOTES: list[dict[str, str]] = [{"title": value, "body": value} for value in PAYLOADS]
# Controls: must be exported exactly as stored.
ORDINARY_NOTES: list[dict[str, str]] = [{"title": "Meeting", "body": "\tindented"}]
EXPORT_FIELDS = ["id", "title", "body", "tags"]


def download_fixture_export() -> bytes:
    """Create the fixture notes in an in-memory app and return GET /notes/export bytes."""
    client = TestClient(create_app(Database(":memory:")))
    for note in FIXTURE_NOTES + ORDINARY_NOTES:
        client.post("/notes", json=note).raise_for_status()
    response = client.get("/notes/export", params={"fields": EXPORT_FIELDS})
    response.raise_for_status()
    content: bytes = response.content
    return content


def write_fixture_csv(path: str | Path) -> Path:
    target = Path(path)
    target.write_bytes(download_fixture_export())
    return target


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: spreadsheet_fixture.py <out.csv>")
    print(write_fixture_csv(sys.argv[1]))

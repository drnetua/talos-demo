"""SQLite storage."""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS tags (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (note_id, tag)
);
"""


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._lock = threading.RLock()

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        """Own the shared connection for a whole unit of work (reentrant)."""
        with self._lock:
            yield self.conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self.session(), self.conn:
            yield self.conn

    def snapshot(self, tag: str | None = None) -> list[dict[str, Any]]:
        """Read matching notes and their tags in one read transaction, fully detached.

        The first SELECT is the snapshot point. Ownership and the transaction are
        released before returning, so callers serialize without holding either.
        """
        with self.session() as conn:
            conn.execute("BEGIN")
            try:
                notes = self._read_notes(conn, tag)
                tags = self._read_tags(conn, tag)
            finally:
                conn.rollback()
        return [{**note, "tags": tags.get(note["id"], [])} for note in notes]

    @staticmethod
    def _read_notes(conn: sqlite3.Connection, tag: str | None) -> list[dict[str, Any]]:
        if tag:
            cursor = conn.execute(
                """SELECT notes.* FROM notes JOIN tags ON tags.note_id = notes.id
                WHERE tags.tag = ? ORDER BY notes.id""",
                (tag.lower(),),
            )
        else:
            cursor = conn.execute("SELECT * FROM notes ORDER BY id")
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _read_tags(conn: sqlite3.Connection, tag: str | None) -> dict[int, list[str]]:
        if tag:
            cursor = conn.execute(
                """SELECT note_id, tag FROM tags
                WHERE note_id IN (SELECT note_id FROM tags WHERE tag = ?)
                ORDER BY note_id, tag""",
                (tag.lower(),),
            )
        else:
            cursor = conn.execute("SELECT note_id, tag FROM tags ORDER BY note_id, tag")
        tags: dict[int, list[str]] = {}
        for row in cursor.fetchall():
            tags.setdefault(row["note_id"], []).append(row["tag"])
        return tags

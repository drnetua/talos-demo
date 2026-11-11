"""HTTP API: notes CRUD, tags, search."""

import os
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, Field

from notes.cursor import decode_cursor, encode_cursor, get_secret
from notes.db import Database


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    tags: list[str] = Field(default_factory=list)


class Note(NoteIn):
    id: int
    created_at: str
    updated_at: str


class NotesPage(BaseModel):
    items: list[Note]
    next_cursor: str | None = None


def create_app(db: Database | None = None) -> FastAPI:
    app = FastAPI(title="talos-demo notes")
    app.state.db = db or Database(os.environ.get("NOTES_DB", "notes.sqlite3"))
    cursor_secret = get_secret()

    def get_db() -> Database:
        database: Database = app.state.db
        return database

    DB = Annotated[Database, Depends(get_db)]

    def load(db: Database, note_id: int) -> Note:
        row = db.conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "note not found")
        tags = [
            r["tag"]
            for r in db.conn.execute(
                "SELECT tag FROM tags WHERE note_id = ? ORDER BY tag", (note_id,)
            )
        ]
        return Note(
            id=row["id"],
            title=row["title"],
            body=row["body"],
            tags=tags,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def set_tags(db: Database, note_id: int, tags: list[str]) -> None:
        db.conn.execute("DELETE FROM tags WHERE note_id = ?", (note_id,))
        for tag in sorted({t.strip().lower() for t in tags if t.strip()}):
            db.conn.execute("INSERT INTO tags (note_id, tag) VALUES (?, ?)", (note_id, tag))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/notes", status_code=201)
    def create(body: NoteIn, db: DB) -> Note:
        with db.tx() as conn:
            cur = conn.execute(
                "INSERT INTO notes (title, body) VALUES (?, ?)", (body.title, body.body)
            )
            note_id = int(cur.lastrowid or 0)
            set_tags(db, note_id, body.tags)
        return load(db, note_id)

    @app.get("/notes", operation_id="list-notes")
    def list_notes(
        db: DB,
        tag: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[str, Query(min_length=1)] | None = None,
    ) -> NotesPage:
        tag_filter = tag.lower() if tag else None
        position = 0
        if cursor is not None:
            try:
                position, _ = decode_cursor(cursor, cursor_secret)
            except ValueError:
                raise HTTPException(422, "invalid page cursor") from None
        if tag_filter:
            rows = db.conn.execute(
                "SELECT note_id AS id FROM tags WHERE tag = ? AND note_id > ?"
                " ORDER BY note_id LIMIT ?",
                (tag_filter, position, limit + 1),
            )
        else:
            rows = db.conn.execute(
                "SELECT id FROM notes WHERE id > ? ORDER BY id LIMIT ?", (position, limit + 1)
            )
        ids = [r["id"] for r in rows.fetchall()]
        page_ids = ids[:limit]
        next_cursor = (
            encode_cursor(page_ids[-1], tag_filter, cursor_secret) if len(ids) > limit else None
        )
        return NotesPage(items=[load(db, i) for i in page_ids], next_cursor=next_cursor)

    @app.get("/notes/search")
    def search(db: DB, q: Annotated[str, Query(min_length=1)]) -> list[Note]:
        like = f"%{q}%"
        rows = db.conn.execute(
            "SELECT id FROM notes WHERE title LIKE ? OR body LIKE ? ORDER BY id", (like, like)
        )
        return [load(db, r["id"]) for r in rows.fetchall()]

    @app.get("/notes/{note_id}")
    def get(note_id: int, db: DB) -> Note:
        return load(db, note_id)

    @app.put("/notes/{note_id}")
    def update(note_id: int, body: NoteIn, db: DB) -> Note:
        load(db, note_id)
        with db.tx() as conn:
            conn.execute(
                "UPDATE notes SET title = ?, body = ?, updated_at = datetime('now') WHERE id = ?",
                (body.title, body.body, note_id),
            )
            set_tags(db, note_id, body.tags)
        return load(db, note_id)

    @app.delete("/notes/{note_id}", status_code=204)
    def delete(note_id: int, db: DB) -> Response:
        load(db, note_id)
        with db.tx() as conn:
            conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return Response(status_code=204)

    @app.get("/tags")
    def tags(db: DB) -> list[dict[str, object]]:
        rows = db.conn.execute("SELECT tag, COUNT(*) AS n FROM tags GROUP BY tag ORDER BY tag")
        return [{"tag": r["tag"], "count": r["n"]} for r in rows]

    @app.post("/notes/{note_id}/tags/{tag}", status_code=201)
    def add_tag(note_id: int, tag: str, db: DB) -> Note:
        note = load(db, note_id)
        with db.tx():
            set_tags(db, note_id, [*note.tags, tag])
        return load(db, note_id)

    @app.delete("/notes/{note_id}/tags/{tag}")
    def remove_tag(note_id: int, tag: str, db: DB) -> Note:
        note = load(db, note_id)
        with db.tx():
            set_tags(db, note_id, [t for t in note.tags if t != tag.lower()])
        return load(db, note_id)

    return app


app = create_app() if os.environ.get("NOTES_AUTOAPP") else None

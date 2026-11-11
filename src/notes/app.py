"""HTTP API: notes CRUD, tags, search, CSV export."""

import csv
import io
import json
import os
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from notes.db import Database

EXPORT_FIELDS = ("id", "title", "body", "tags", "created_at", "updated_at")


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    tags: list[str] = Field(default_factory=list)


class Note(NoteIn):
    id: int
    created_at: str
    updated_at: str


def create_app(db: Database | None = None) -> FastAPI:
    app = FastAPI(title="talos-demo notes")
    app.state.db = db or Database(os.environ.get("NOTES_DB", "notes.sqlite3"))

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

    @app.get("/notes")
    def list_notes(db: DB, tag: str | None = None) -> list[Note]:
        if tag:
            rows = db.conn.execute(
                "SELECT note_id AS id FROM tags WHERE tag = ? ORDER BY note_id", (tag.lower(),)
            )
        else:
            rows = db.conn.execute("SELECT id FROM notes ORDER BY id")
        return [load(db, r["id"]) for r in rows.fetchall()]

    @app.get("/notes/search")
    def search(db: DB, q: Annotated[str, Query(min_length=1)]) -> list[Note]:
        like = f"%{q}%"
        rows = db.conn.execute(
            "SELECT id FROM notes WHERE title LIKE ? OR body LIKE ? ORDER BY id", (like, like)
        )
        return [load(db, r["id"]) for r in rows.fetchall()]

    def export_notes(db: Database, selected: list[str], tag: str | None) -> Response:
        columns = [field for field in EXPORT_FIELDS if field in selected]
        if tag:
            rows = db.conn.execute(
                """SELECT notes.* FROM notes JOIN tags ON tags.note_id = notes.id
                WHERE tags.tag = ? ORDER BY notes.id""",
                (tag.lower(),),
            ).fetchall()
        else:
            rows = db.conn.execute("SELECT * FROM notes ORDER BY id").fetchall()

        tags_by_id: dict[int, list[str]] = {}
        for tag_row in db.conn.execute("SELECT note_id, tag FROM tags ORDER BY note_id, tag"):
            tags_by_id.setdefault(tag_row["note_id"], []).append(tag_row["tag"])

        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(columns)
        for row in rows:
            values = {field: row[field] for field in columns if field != "tags"}
            if "tags" in columns:
                values["tags"] = json.dumps(
                    tags_by_id.get(row["id"], []), separators=(",", ":")
                )
            writer.writerow([values[field] for field in columns])

        return Response(
            content=output.getvalue().encode(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="notes.csv"',
                "Cache-Control": "no-store",
            },
        )

    @app.get(
        "/notes/export",
        operation_id="export-notes",
        responses={
            200: {
                "description": "Complete UTF-8 CSV with selected headings; may have zero records.",
                "content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}},
                "headers": {
                    "Content-Disposition": {
                        "required": True,
                        "schema": {"type": "string", "const": 'attachment; filename="notes.csv"'},
                    },
                    "Cache-Control": {
                        "required": True,
                        "schema": {"type": "string", "const": "no-store"},
                    },
                },
            },
            422: {
                "description": "Invalid field selection or repeated tag; no attachment.",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/HTTPValidationError"}
                    }
                },
            },
        },
    )
    def export(
        request: Request,
        db: DB,
        fields: Annotated[
            list[str],
            Query(
                description="Repeat for each field; duplicate fields are exported once.",
                json_schema_extra={
                    "minItems": 1,
                    "items": {"type": "string", "enum": list(EXPORT_FIELDS)},
                },
            ),
        ],
        tag: Annotated[
            str | None,
            Query(description="At most one tag; omitted or empty selects all notes."),
        ] = None,
    ) -> Response:
        if len(request.query_params.getlist("tag")) > 1:
            raise HTTPException(
                422,
                detail=[
                    {
                        "loc": ["query", "tag"],
                        "msg": "Only one tag is supported",
                        "type": "value_error",
                    }
                ],
            )
        errors = [
            {
                "loc": ["query", "fields", index],
                "msg": (
                    "Export field must not be empty"
                    if not field
                    else f"Unknown export field: {field}"
                ),
                "type": "value_error",
                "input": field,
            }
            for index, field in enumerate(fields)
            if field not in EXPORT_FIELDS
        ]
        if errors:
            raise HTTPException(422, detail=errors)
        return export_notes(db, fields, tag)

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

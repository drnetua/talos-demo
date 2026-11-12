"""HTTP API: notes CRUD, tags, search, CSV export."""

import csv
import io
import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from notes.cursor import decode_cursor, encode_cursor, get_secret
from notes.db import Database
from notes.safe_text import safe_cell

EXPORT_FAILURE_DETAIL = "Export could not be completed"
EXPORT_DESCRIPTION = (
    "Downloads one complete CSV of all notes or of a single tag, without pagination. "
    "Safe text rule: a title, body or tags cell whose first character after any leading "
    "whitespace or control characters is =, +, - or @ is exported with one leading "
    "apostrophe (') so spreadsheets do not treat it as a formula; other values are exported "
    "unchanged. Stored notes are not changed."
)
UI_DIR = Path(__file__).parent / "ui"
UI_ASSETS = {"app.css": "text/css", "app.js": "text/javascript"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CROSS_SITE_DETAIL = "cross-site request rejected"
DEFAULT_PORTS = {"http": "80", "https": "443"}
EXPORT_FIELDS = ("id", "title", "body", "tags", "created_at", "updated_at")


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    tags: list[str] = Field(default_factory=list)


class Note(NoteIn):
    id: int
    created_at: str
    updated_at: str


class ExportErrorResponse(BaseModel):
    detail: Literal["Export could not be completed"]


class NotesPage(BaseModel):
    items: list[Note]
    next_cursor: str | None = None


def capture_notes(db: Database, tag: str | None) -> list[dict[str, Any]]:
    """Seam for the detached snapshot capture (tests wrap it)."""
    return db.snapshot(tag)


def normalise_origin(scheme: str, host: str) -> str:
    """Scheme and host[:port] lower-cased, with the default port dropped."""
    host = host.lower()
    default = DEFAULT_PORTS.get(scheme.lower())
    if default and host.endswith(f":{default}"):
        host = host[: -len(f":{default}")]
    return f"{scheme.lower()}://{host}"


def is_cross_site(request: Request) -> bool:
    """Decision order: Sec-Fetch-Site, then Origin, else pass (curl and scripts)."""
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None:
        return fetch_site.strip().lower() == "cross-site"
    origin = request.headers.get("origin")
    if origin is None:
        return False
    scheme, sep, host = origin.strip().partition("://")
    if not sep:
        return True
    own = normalise_origin(request.url.scheme, request.headers.get("host", ""))
    return normalise_origin(scheme, host) != own


def create_app(db: Database | None = None) -> FastAPI:
    app = FastAPI(title="talos-demo notes")
    app.state.db = db or Database(os.environ.get("NOTES_DB", "notes.sqlite3"))
    cursor_secret = get_secret()

    @app.middleware("http")
    async def reject_cross_site_writes(request: Request, call_next: Any) -> Response:
        if request.method in UNSAFE_METHODS and is_cross_site(request):
            return JSONResponse(status_code=403, content={"detail": CROSS_SITE_DETAIL})
        response: Response = await call_next(request)
        return response

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

    @app.get("/", include_in_schema=False)
    def ui_page() -> FileResponse:
        return FileResponse(
            UI_DIR / "index.html", media_type="text/html", headers={"Cache-Control": "no-cache"}
        )

    @app.get("/ui/{asset}", include_in_schema=False)
    def ui_asset(asset: str) -> FileResponse:
        media_type = UI_ASSETS.get(asset)
        if media_type is None:
            raise HTTPException(404, "asset not found")
        return FileResponse(
            UI_DIR / asset, media_type=media_type, headers={"Cache-Control": "no-cache"}
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/notes", status_code=201)
    def create(body: NoteIn, db: DB) -> Note:
        with db.session():
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
        cursor: Annotated[str, Query(json_schema_extra={"minLength": 1})] | None = None,
    ) -> NotesPage:
        tag_filter = tag.lower() if tag else None
        position = 0
        if cursor is not None:
            try:
                position, cursor_tag = decode_cursor(cursor, cursor_secret)
            except (ValueError, TypeError):  # TypeError: non-ASCII text in compare_digest
                raise HTTPException(422, "invalid page cursor") from None
            if cursor_tag != tag_filter:
                raise HTTPException(422, "page cursor does not match the tag filter")
        with db.session() as conn:
            if tag_filter:
                rows = conn.execute(
                    "SELECT note_id AS id FROM tags WHERE tag = ? AND note_id > ?"
                    " ORDER BY note_id LIMIT ?",
                    (tag_filter, position, limit + 1),
                )
            else:
                rows = conn.execute(
                    "SELECT id FROM notes WHERE id > ? ORDER BY id LIMIT ?",
                    (position, limit + 1),
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
        with db.session() as conn:
            rows = conn.execute(
                "SELECT id FROM notes WHERE title LIKE ? OR body LIKE ? ORDER BY id",
                (like, like),
            )
            return [load(db, r["id"]) for r in rows.fetchall()]

    def export_notes(db: Database, selected: list[str], tag: str | None) -> Response:
        columns = [field for field in EXPORT_FIELDS if field in selected]
        try:
            notes = capture_notes(db, tag)
            return csv_response(columns, notes)
        except Exception:
            return JSONResponse(status_code=500, content={"detail": EXPORT_FAILURE_DETAIL})

    def csv_response(columns: list[str], notes: list[dict[str, Any]]) -> Response:
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(columns)
        for row in notes:
            values = {field: str(row[field]) for field in columns if field != "tags"}
            if "tags" in columns:
                values["tags"] = json.dumps(row["tags"], separators=(",", ":"))
            writer.writerow([safe_cell(values[field]) for field in columns])

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
        description=EXPORT_DESCRIPTION,
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
            500: {
                "description": "Export could not be completed; no attachment.",
                "model": ExportErrorResponse,
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
        with db.session():
            return load(db, note_id)

    @app.put("/notes/{note_id}")
    def update(note_id: int, body: NoteIn, db: DB) -> Note:
        with db.session():
            load(db, note_id)
            with db.tx() as conn:
                conn.execute(
                    "UPDATE notes SET title = ?, body = ?, updated_at = datetime('now') "
                    "WHERE id = ?",
                    (body.title, body.body, note_id),
                )
                set_tags(db, note_id, body.tags)
            return load(db, note_id)

    @app.delete("/notes/{note_id}", status_code=204)
    def delete(note_id: int, db: DB) -> Response:
        with db.session():
            load(db, note_id)
            with db.tx() as conn:
                conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        return Response(status_code=204)

    @app.get("/tags")
    def tags(db: DB) -> list[dict[str, object]]:
        with db.session() as conn:
            rows = conn.execute(
                "SELECT tag, COUNT(*) AS n FROM tags GROUP BY tag ORDER BY tag"
            ).fetchall()
        return [{"tag": r["tag"], "count": r["n"]} for r in rows]

    @app.post("/notes/{note_id}/tags/{tag}", status_code=201)
    def add_tag(note_id: int, tag: str, db: DB) -> Note:
        with db.session():
            note = load(db, note_id)
            with db.tx():
                set_tags(db, note_id, [*note.tags, tag])
            return load(db, note_id)

    @app.delete("/notes/{note_id}/tags/{tag}")
    def remove_tag(note_id: int, tag: str, db: DB) -> Note:
        with db.session():
            note = load(db, note_id)
            with db.tx():
                set_tags(db, note_id, [t for t in note.tags if t != tag.lower()])
            return load(db, note_id)

    return app


app = create_app() if os.environ.get("NOTES_AUTOAPP") else None

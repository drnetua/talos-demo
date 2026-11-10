# talos-demo

Test project for TalosSDLC runs (roadmap SP4): a small notes service with tags.

| Method | Path | What |
|---|---|---|
| GET | /health | liveness |
| POST | /notes | create a note (title, body, tags) |
| GET | /notes?tag= | list, optionally by tag |
| GET | /notes/search?q= | search in title and body |
| GET / PUT / DELETE | /notes/{id} | read, update, delete |
| GET | /tags | tags with counts |
| POST / DELETE | /notes/{id}/tags/{tag} | add / remove a tag |

```bash
uv sync
uv run pytest
NOTES_AUTOAPP=1 uv run uvicorn notes.app:app --reload
```

## Seed ideas for TalosSDLC runs (size feature)

1. **Pagination** — `GET /notes` returns pages (`limit`, `cursor`) instead of everything.
2. **Export to CSV** — download all notes (or a tag) as CSV.
3. **Tag autocomplete** — suggest existing tags by prefix while typing.
4. **Pinned notes** — pin notes so they come first in lists.
5. **Soft delete with restore** — deleted notes go to a trash for 30 days.

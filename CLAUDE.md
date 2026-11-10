# talos-demo

Notes with tags: FastAPI + SQLite, Python 3.12, uv.

- Code: `src/notes/` (`app.py` — HTTP API, `db.py` — SQLite schema).
- Checks: `uv run ruff check .`, `uv run mypy`, `uv run pytest` (coverage ≥ 80 %).
- Run: `NOTES_AUTOAPP=1 uv run uvicorn notes.app:app --reload`.
- Conventions: small functions, typed code, tests for every endpoint.

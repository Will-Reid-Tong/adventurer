# Design decisions

Settled decisions for the project, recorded for reference.

## Stack

- **uv** for dependency management and the project environment.
- **Flask** app factory (`adventurer:create_app()`) so the app can be built for tests
  and for gunicorn without import-time side effects.
- **gunicorn** as the production WSGI server.
- Python **3.14**, `src` layout, package `adventurer`.

## Data

- **SQLite** with raw SQL via the stdlib `sqlite3` — no ORM, no query builder.
- `schema.sql` is the single source of truth for the data model and is applied
  idempotently (`CREATE TABLE IF NOT EXISTS`).
- Images are stored as **BLOBs** in SQLite, not on the filesystem. The single
  database file is the entire persistent state.
- Foreign keys are enabled per connection (`PRAGMA foreign_keys = ON`).

## Frontend

- The player is a **single HTML page with vanilla JS** — no framework, no build
  step.
- The admin UI is **server-rendered Jinja**, with at most a sliver of vanilla JS
  for image preview.
- The admin graph map is **vertical HTML cards**, not SVG and not draggable.

## Tooling

- **ruff** for lint + format, line length 90, target py314.
- **ty** in strict mode for type checking.
- **pytest** discovers tests under `tests/`.

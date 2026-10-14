# Choose Your Own Adventure

A small self-hosted choose-your-own-adventure engine: an SQLite-backed Flask app
with a vanilla-JS player and a server-rendered admin.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.14 (uv can provision it: `uv python install 3.14`)

## Run

```sh
uv sync
uv run gunicorn -w 2 -b 0.0.0.0:8000 'cyoa:create_app()'
```

On first start the database is initialized and an admin login is seeded from
the `ADMIN_USERNAME` / `ADMIN_PASSWORD` environment variables. Both default to
`admin` / `admin` for development — set them in any deployment you care about.

## Development

```sh
uv sync
uv run pytest
uv run ruff check
uv run ruff format --check
uv run ty check
```

## Layout

- `src/cyoa/` — application package (`create_app()` factory).
- `tests/` — pytest suite.
- `docs/decisions.md` — settled design decisions.

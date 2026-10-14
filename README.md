# Adventurer

Adventurer is a small self-hosted choose-your-own-adventure engine: an
SQLite-backed Flask app with a vanilla-JS player and a server-rendered admin.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Python 3.14 (uv can provision it: `uv python install 3.14`)

## Run

```sh
uv sync
uv run gunicorn -w 2 -b 0.0.0.0:8000 'adventurer:create_app()'
```

On first start the database is initialized and an admin login is seeded from
the `ADMIN_USERNAME` / `ADMIN_PASSWORD` environment variables. Both default to
`admin` / `admin` for development — set them in any deployment you care about.

## Run with Docker Compose

```sh
mkdir -p data
# On Linux the container (uid 1001) must own the bind-mounted data directory.
sudo chown -R 1001:1001 data
ADMIN_USERNAME=you ADMIN_PASSWORD=change-me docker compose up -d --build
```

The player is at <http://localhost:8000> and the admin at
<http://localhost:8000/admin>. Drop `--build` to pull the published GHCR image
instead of building from source. `ADMIN_USERNAME` / `ADMIN_PASSWORD` may also be
set in a `.env` file next to `docker-compose.yml`.

### Backup and restore

The whole database, image BLOBs included, is the single file `data/app.db`,
bind-mounted from the host. Stop the app first for a consistent snapshot:

```sh
mkdir -p backups
docker compose stop app
cp data/app.db "backups/app-$(date +%F).db"
docker compose start app
```

Restore by copying a backup over `data/app.db` while the app is stopped.

## Development

```sh
uv sync
uv run pytest
uv run ruff check
uv run ruff format --check
uv run ty check
```

## Layout

- `src/adventurer/` — application package (`create_app()` factory).
- `tests/` — pytest suite.
- `docs/decisions.md` — settled design decisions.

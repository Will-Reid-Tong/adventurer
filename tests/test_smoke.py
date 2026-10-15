"""Adventure frontend seam: ``GET /`` serves the single-page player app.

Pins the routing contract:

- when the adventure has pages, ``GET /`` returns the player HTML
  (200, ``text/html``) that wires vanilla JS to the API contract
  (``/api/start``, ``/api/pages/<id>``, ``POST /api/pages/<id>/roll``), with or
  without an explicit ``start_page_id``;
- only an empty database redirects ``GET /`` to the login page so a fresh
  install sends the operator somewhere useful;
- no JS framework or build step is introduced.
"""

from pathlib import Path
from urllib.parse import urlsplit

from adventurer import create_app, db

REPO_ROOT = Path(__file__).resolve().parents[1]


def _seed_app(db_path: str, *, with_page: bool, start_page_id: int | None = None) -> None:
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        if with_page:
            conn.execute(
                "INSERT INTO pages (id, type, title, body_text) "
                "VALUES (1, 'choice', 'Start', 'You are at the start.')"
            )
        if start_page_id is not None:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('start_page_id', ?)",
                (str(start_page_id),),
            )


def test_get_root_redirects_to_login_when_no_pages(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "app.db")
    _seed_app(db_path, with_page=False)
    monkeypatch.setenv("DATABASE_PATH", db_path)

    response = create_app().test_client().get("/")

    assert response.status_code == 302
    assert urlsplit(response.headers["Location"]).path == "/login"


def test_get_root_serves_player_when_pages_exist_without_start(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = str(tmp_path / "app.db")
    _seed_app(db_path, with_page=True)
    monkeypatch.setenv("DATABASE_PATH", db_path)

    response = create_app().test_client().get("/")

    # Content exists, so the home page is the playable quiz even before an
    # admin has picked an explicit start page.
    assert response.status_code == 200
    assert response.mimetype == "text/html"


def test_get_root_serves_player_app_at_api_seam(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "app.db")
    _seed_app(db_path, with_page=True, start_page_id=1)
    monkeypatch.setenv("DATABASE_PATH", db_path)

    response = create_app().test_client().get("/")

    assert response.status_code == 200
    assert response.mimetype == "text/html"

    # The client must drive the same API surface the player endpoints expose.
    html = response.get_data(as_text=True)
    assert "/api/start" in html
    assert "/api/pages/" in html
    assert "/roll" in html

    # Vanilla JS only: no framework and no build step.
    assert not (REPO_ROOT / "package.json").exists()

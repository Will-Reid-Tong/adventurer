"""Admin settings seam: the settings routes.

Pins the Issue #9 acceptance criteria:

- the settings form (``GET /admin/settings``) lists the existing pages so an
  admin can pick one as the start page;
- ``POST /admin/settings`` with a valid ``start_page_id`` persists it, and the
  player contract ``GET /api/start`` (#3) returns it;
- an invalid ``start_page_id`` is rejected with a visible error and leaves the
  stored setting unchanged;
- changing the password re-hashes and stores it, so the old credential no
  longer logs in and the new one does.

The route sits behind the admin login (#6), so the test seeds
``admin_username`` / ``admin_password_hash`` through the ``cyoa.db`` seam and
logs in before touching ``/admin/settings``. Form fields are ``start_page_id``
and ``password``.
"""

from pathlib import Path
from urllib.parse import urlsplit

from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.test import TestResponse

from cyoa import create_app, db

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a brand new passphrase"


def _redirects_to_login(response: TestResponse) -> bool:
    """True when ``response`` is a 302 pointing at the login page."""
    return (
        response.status_code == 302
        and urlsplit(response.headers["Location"]).path == "/login"
    )


def test_admin_settings_seam(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "app.db")
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('admin_username', ?)",
            (ADMIN_USERNAME,),
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('admin_password_hash', ?)",
            (generate_password_hash(ADMIN_PASSWORD),),
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) "
            "VALUES (1, 'choice', 'Cave Entrance', 'Two tunnels diverge.')"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) "
            "VALUES (2, 'ending', 'The End', 'You found daylight.')"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()

    # Guarded like every /admin/* route: unauthenticated -> login page.
    assert _redirects_to_login(client.get("/admin/settings"))

    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    # The form offers the existing pages to choose a start page from.
    form = client.get("/admin/settings")
    assert form.status_code == 200
    assert b"Cave Entrance" in form.data
    assert b"The End" in form.data

    # Setting a valid start page persists it and the player API returns it.
    saved = client.post("/admin/settings", data={"start_page_id": "2"})
    assert saved.status_code == 302
    assert client.get("/api/start").get_json() == {"page_id": 2}

    # An invalid start page id is rejected (not a success redirect) with a
    # visible error, and the stored setting is unchanged.
    rejected = client.post("/admin/settings", data={"start_page_id": "9999"})
    assert rejected.status_code == 200
    assert b"start" in rejected.data.lower()
    assert client.get("/api/start").get_json() == {"page_id": 2}

    # Changing the password re-hashes and stores it.
    changed = client.post(
        "/admin/settings",
        data={"start_page_id": "2", "password": NEW_PASSWORD},
    )
    assert changed.status_code == 302
    with db.connect(db_path) as conn:
        stored = conn.execute(
            "SELECT value FROM settings WHERE key = 'admin_password_hash'"
        ).fetchone()["value"]
    assert check_password_hash(stored, NEW_PASSWORD)
    assert not check_password_hash(stored, ADMIN_PASSWORD)

    # The old credential no longer establishes a session ...
    client.post("/logout")
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert _redirects_to_login(client.get("/admin/settings"))

    # ... while the new credential does.
    client.post("/login", data={"username": ADMIN_USERNAME, "password": NEW_PASSWORD})
    assert client.get("/admin/settings").status_code == 200

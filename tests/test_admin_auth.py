"""Admin authentication seam: ``POST /login``, ``POST /logout``, admin guard.

Pins the Issue #6 acceptance criteria:

- wrong password rejected (no session established);
- correct credentials establish a session that admits requests to ``/admin/*``;
- an unauthenticated request to any ``/admin/*`` route redirects to the login
  page;
- ``POST /logout`` clears the session so ``/admin/*`` is guarded again.

The single existing admin route, ``POST /admin/images`` (#5), is the ``/admin/*``
probe used here; this slice is what puts it behind the guard.
"""

from pathlib import Path
from urllib.parse import urlsplit

from werkzeug.security import generate_password_hash
from werkzeug.test import TestResponse

from cyoa import create_app, db

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct horse battery staple"


def _redirects_to_login(response: TestResponse) -> bool:
    """True when ``response`` is a 302 pointing at the login page."""
    return (
        response.status_code == 302
        and urlsplit(response.headers["Location"]).path == "/login"
    )


def test_admin_auth_login_logout_guard_seam(tmp_path: Path, monkeypatch) -> None:
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

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()

    # Unauthenticated requests to /admin/* -> redirect to the login page.
    assert _redirects_to_login(client.post("/admin/images"))
    assert _redirects_to_login(client.get("/admin/images"))

    # Wrong password -> rejected: the session stays unauthenticated.
    client.post(
        "/login", data={"username": ADMIN_USERNAME, "password": "not-the-password"}
    )
    assert _redirects_to_login(client.post("/admin/images"))

    # Correct credentials -> a session is established and the guard admits the
    # request: the view runs and rejects the missing file with 400, rather than
    # bouncing back to /login.
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})
    assert client.post("/admin/images").status_code == 400

    # Logout clears the session -> /admin/* is guarded again.
    client.post("/logout")
    assert _redirects_to_login(client.post("/admin/images"))

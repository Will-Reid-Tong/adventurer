"""Regression tests for the code-review findings.

Each test pins one of the gaps found in review: the default RNG, the admin
page image upload/replace path, the first-run admin bootstrap, the unreachable-
page depth, and the map connectors.
"""

import base64
import io
import random
from pathlib import Path

from werkzeug.security import generate_password_hash

from adventurer import create_app, db
from adventurer.bootstrap import bootstrap_admin
from adventurer.graph import build_graph

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct horse battery staple"

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _seed_admin(db_path: str) -> None:
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


def test_create_app_sets_default_rng(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    app = create_app()
    # A default RNG means chance rolls work under gunicorn without any setup.
    assert isinstance(app.config["RNG"], random.Random)


def test_page_image_upload_then_replacement(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "app.db")
    _seed_admin(db_path)
    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    created = client.post(
        "/admin/pages/new",
        data={
            "title": "Cover",
            "type": "choice",
            "body_text": "Body.",
            "image": (io.BytesIO(PNG_BYTES), "one.png", "image/png"),
        },
        content_type="multipart/form-data",
    )
    assert created.status_code == 302
    with db.connect(db_path) as conn:
        page = conn.execute("SELECT id, image_id FROM pages").fetchone()
        first = conn.execute("SELECT id, filename FROM images").fetchone()
    assert page["image_id"] == first["id"]
    assert first["filename"] == "one.png"
    page_id = page["id"]

    replaced = client.post(
        f"/admin/pages/{page_id}/edit",
        data={
            "title": "Cover",
            "type": "choice",
            "body_text": "Body.",
            "image": (io.BytesIO(PNG_BYTES), "two.png", "image/png"),
        },
        content_type="multipart/form-data",
    )
    assert replaced.status_code == 302
    with db.connect(db_path) as conn:
        page = conn.execute(
            "SELECT image_id FROM pages WHERE id = ?", (page_id,)
        ).fetchone()
        rows = conn.execute("SELECT id, filename FROM images ORDER BY id").fetchall()
    # Replacement inserts a new row and repoints pages.image_id; the old image
    # row is left in place for later garbage collection.
    assert [row["filename"] for row in rows] == ["one.png", "two.png"]
    assert page["image_id"] == rows[1]["id"]


def test_first_run_admin_bootstrap(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "app.db")
    db.init_db(db_path)
    monkeypatch.setenv("DATABASE_PATH", db_path)
    monkeypatch.setenv("ADMIN_USERNAME", "proprietor")
    monkeypatch.setenv("ADMIN_PASSWORD", "open sesame")

    bootstrap_admin(db_path)
    with db.connect(db_path) as conn:
        assert db.get_setting(conn, "admin_username") == "proprietor"

    client = create_app().test_client()
    logged_in = client.post(
        "/login", data={"username": "proprietor", "password": "open sesame"}
    )
    assert logged_in.status_code == 302


def test_unreachable_pages_get_a_depth_after_the_reachable_graph(tmp_path: Path) -> None:
    db_path = str(tmp_path / "app.db")
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('start_page_id', '1')")
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) "
            "VALUES (1, 'choice', 'Start', 'Start.')"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) "
            "VALUES (2, 'ending', 'Orphan', 'Unreachable.')"
        )
        graph = build_graph(conn)
    depths = {node["id"]: node["depth"] for node in graph["nodes"]}
    assert depths[1] == 0
    assert depths[2] > depths[1]


def test_map_draws_connectors_and_reentrant_dashes(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "app.db")
    _seed_admin(db_path)
    with db.connect(db_path) as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('start_page_id', '1')")
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (1, 'choice', 'Start', 'Start.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'chance', 'Right', 'Right.', 1)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (3, 'ending', 'End', 'End.', 2)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, position) "
            "VALUES (1, 2, 'Right', 0)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, weight, position) "
            "VALUES (2, 3, NULL, 60, 0)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, weight, position) "
            "VALUES (2, 1, NULL, 40, 1)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    html = client.get("/admin/map").get_data(as_text=True)
    # One connector per edge, with the cycle back to the root drawn dashed.
    assert html.count("<line") == 3
    assert "map__edge--reentrant" in html

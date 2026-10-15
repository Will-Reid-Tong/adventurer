"""Admin page CRUD seam: the list / new / edit / delete routes.

Pins the Issue #7 acceptance criteria:

- the test client exercises the full CRUD flow (list, create, edit, delete);
- deleting a page cascades to delete that page's options (FK
  ``ON DELETE CASCADE``);
- an invalid ``type`` is rejected with a visible error and nothing is written.

The routes are server-rendered Jinja and sit behind the admin login (#6), so
the test seeds ``admin_username`` / ``admin_password_hash`` through the
``adventurer.db`` seam and logs in before touching ``/admin/*``.
"""

import re
from pathlib import Path

from werkzeug.security import generate_password_hash

from adventurer import create_app, db

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct horse battery staple"


def test_admin_page_crud_seam(tmp_path: Path, monkeypatch) -> None:
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
        # Two pages in a known position order; page 1 owns an option so the
        # cascade on delete is observable.
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (1, 'choice', 'Open Door', 'A door stands open.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'The End', 'You have arrived.', 1)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, position) "
            "VALUES (1, 2, 'Step through', 0)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    # List: 200, ordered by position.
    listing = client.get("/admin/pages")
    assert listing.status_code == 200
    assert b"Open Door" in listing.data
    assert b"The End" in listing.data
    assert listing.data.index(b"Open Door") < listing.data.index(b"The End")

    # New form renders.
    assert client.get("/admin/pages/new").status_code == 200

    # Create: the page is persisted.
    created = client.post(
        "/admin/pages/new",
        data={"title": "Third Page", "type": "choice", "body_text": "A new path."},
        follow_redirects=True,
    )
    assert created.status_code == 200
    with db.connect(db_path) as conn:
        new_page = conn.execute(
            "SELECT id, title, type, body_text FROM pages WHERE title = 'Third Page'"
        ).fetchone()
    assert new_page is not None
    assert new_page["type"] == "choice"
    assert new_page["body_text"] == "A new path."
    new_id = new_page["id"]

    # Edit: the form shows current values, then the update is persisted.
    edit_form = client.get(f"/admin/pages/{new_id}/edit")
    assert edit_form.status_code == 200
    assert b"Third Page" in edit_form.data
    edited = client.post(
        f"/admin/pages/{new_id}/edit",
        data={"title": "Renamed", "type": "ending", "body_text": "The path ends."},
        follow_redirects=True,
    )
    assert edited.status_code == 200
    with db.connect(db_path) as conn:
        row = conn.execute(
            "SELECT title, type, body_text FROM pages WHERE id = ?", (new_id,)
        ).fetchone()
    assert (row["title"], row["type"], row["body_text"]) == (
        "Renamed",
        "ending",
        "The path ends.",
    )

    # Invalid type: rejected with a visible error and no row written.
    rejected = client.post(
        "/admin/pages/new",
        data={"title": "Bogus", "type": "sorcery", "body_text": "?"},
        follow_redirects=True,
    )
    assert rejected.status_code == 200
    assert b"invalid type" in rejected.data.lower()
    with db.connect(db_path) as conn:
        bogus_count = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE title = 'Bogus'"
        ).fetchone()[0]
    assert bogus_count == 0

    # Delete cascades to the deleted page's options.
    deleted = client.post("/admin/pages/1/delete", follow_redirects=True)
    assert deleted.status_code == 200
    with db.connect(db_path) as conn:
        page_count = conn.execute("SELECT COUNT(*) FROM pages WHERE id = 1").fetchone()[0]
        option_count = conn.execute(
            "SELECT COUNT(*) FROM options WHERE page_id = 1"
        ).fetchone()[0]
    assert page_count == 0
    assert option_count == 0


def test_new_page_gets_the_next_position(tmp_path: Path, monkeypatch) -> None:
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
        # Existing pages occupy positions 0 and 1 so the next free slot is 2.
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (1, 'choice', 'First', 'First.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'Second', 'Second.', 1)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    client.post(
        "/admin/pages/new",
        data={"title": "Third", "type": "choice", "body_text": "Third."},
    )
    client.post(
        "/admin/pages/new",
        data={"title": "Fourth", "type": "ending", "body_text": "Fourth."},
    )

    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT title, position FROM pages ORDER BY position"
        ).fetchall()
    assert [(row["title"], row["position"]) for row in rows] == [
        ("First", 0),
        ("Second", 1),
        ("Third", 2),
        ("Fourth", 3),
    ]


def test_admin_pages_list_shows_position(tmp_path: Path, monkeypatch) -> None:
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
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (1, 'choice', 'Open Door', 'A door stands open.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'The End', 'You have arrived.', 1)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, position) "
            "VALUES (1, 2, 'Step through', 0)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    html = client.get("/admin/pages").get_data(as_text=True)

    # Each management row shows its position (1-based) so the operator sees
    # where each page sits in the adventure's order. Structure itself is read
    # off the graph above the list, not this flat summary.
    assert "#1" in html and "#2" in html


def test_admin_pages_view_renders_children_in_parallel(
    tmp_path: Path, monkeypatch
) -> None:
    """A choice's children sit side by side beneath it, each linking to its editor.

    Regression: the page list rendered a choice's targets inline as
    ``-> B -> C``, which reads as B linking to C. The view must use the graph
    layout instead, so both children land on the same row and each is connected
    to its parent by its own downward arrow.
    """
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
        conn.execute("INSERT INTO settings (key, value) VALUES ('start_page_id', '1')")
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (1, 'choice', 'Fork', 'Pick a way.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'Left End', 'Left.', 1)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (3, 'ending', 'Right End', 'Right.', 2)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, position) "
            "VALUES (1, 2, 'Left', 0)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, position) "
            "VALUES (1, 3, 'Right', 1)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    html = client.get("/admin/pages").get_data(as_text=True)

    # The structure is drawn as a graph, not a flat list.
    assert 'class="map__edges"' in html

    cards = {
        int(page_id): (int(x), int(y))
        for x, y, page_id in re.findall(
            r'<a class="node[^>]*?style="left: (\d+)px; top: (\d+)px;[^>]*?'
            r'href="/admin/pages/(\d+)/edit"',
            html,
        )
    }
    assert set(cards) == {1, 2, 3}

    # The root sits above its children.
    assert cards[1][1] < cards[2][1]
    # The two children share a row (same top), in different columns, so
    # neither is drawn as connecting to the other.
    assert cards[2][1] == cards[3][1]
    assert cards[2][0] != cards[3][0]

    # Every page, children included, links to its editor.
    for page_id in (1, 2, 3):
        assert f'href="/admin/pages/{page_id}/edit"' in html

    # The choice owns two connectors: both leave the root and point down to a
    # child, rather than chaining the children to each other.
    lines = re.findall(
        r'<line class="map__edge[^"]*"\s+x1="([\d.]+)" y1="([\d.]+)"\s+'
        r'x2="([\d.]+)" y2="([\d.]+)"',
        html,
    )
    assert len(lines) == 2
    assert all(float(y2) > float(y1) for _x1, y1, _x2, y2 in lines)
    assert len({x1 for x1, _y1, _x2, _y2 in lines}) == 1

    # The old inline "-> target" rendering is gone.
    assert "\u2192 Left End" not in html
    assert "\u2192 Right End" not in html

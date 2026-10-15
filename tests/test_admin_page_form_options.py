"""Admin page form: the options panel on create/edit.

The page create/edit form is the seam at which the operator sees and mutates
the page's outgoing options. The backend already has option CRUD endpoints
(``/admin/pages/<id>/options/...``); these tests pin the rendered HTML that
ties those endpoints to the form.

Slice 1 pins the rendered HTML on the edit form: each existing option shows
inline editable fields (label, target dropdown, weight) with its own save
and delete buttons, and an "add option" form whose target is a <select> of
every page. The page-type specific rules (choice vs chance vs ending) and
the validation behaviour are already pinned by ``test_admin_options.py``.
"""

from pathlib import Path

from werkzeug.security import generate_password_hash

from adventurer import create_app, db

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct horse battery staple"


def test_edit_form_renders_existing_options_inline_with_add_form(
    tmp_path: Path, monkeypatch
) -> None:
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

    html = client.get("/admin/pages/1/edit").get_data(as_text=True)

    # The existing option's label is rendered as the inline edit field value.
    assert 'value="Step through"' in html
    # The option's target is preselected in a <select name="target_page_id">.
    # Both pages are listed (page 1 itself included; self-targets are allowed).
    assert html.count('<select name="target_page_id">') >= 2
    assert 'value="1">Open Door' in html
    assert '<option value="2" selected>The End' in html
    # An inline edit form for the option points at the edit endpoint.
    assert 'action="/admin/pages/1/options/1/edit"' in html
    assert 'method="post"' in html
    # A delete form for the option points at the delete endpoint.
    assert 'action="/admin/pages/1/options/1/delete"' in html
    # An "add option" form is present and points at the new-option endpoint.
    assert 'action="/admin/pages/1/options/new"' in html


def test_edit_form_hides_options_panel_for_ending_page(
    tmp_path: Path, monkeypatch
) -> None:
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
            "VALUES (1, 'ending', 'The End', 'You have arrived.', 0)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    html = client.get("/admin/pages/1/edit").get_data(as_text=True)

    # The options panel is hidden entirely on an ending page (matches the
    # ERR_ENDING_OPTIONS rule: ending pages cannot have options).
    assert "/options/" not in html
    assert '<select name="target_page_id">' not in html


def test_new_page_form_renders_initial_option_fields(tmp_path: Path, monkeypatch) -> None:
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
            "VALUES (1, 'ending', 'The End', 'You have arrived.', 0)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    html = client.get("/admin/pages/new").get_data(as_text=True)

    # Initial option fields are siblings of the page fields (no separate
    # <form> wrapper) so the operator can create a page with one option in
    # a single POST. Field names match the option-CRUD endpoints so the same
    # form values are valid for both edit and create flows.
    assert 'name="label"' in html
    assert 'name="target_page_id"' in html
    assert 'name="weight"' in html
    # The target dropdown lists every page so the operator can pick a target
    # at create time.
    assert 'value="1">The End' in html


def test_new_page_post_creates_initial_option_in_one_request(
    tmp_path: Path, monkeypatch
) -> None:
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
            "VALUES (1, 'ending', 'The End', 'You have arrived.', 0)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    response = client.post(
        "/admin/pages/new",
        data={
            "title": "Open Door",
            "type": "choice",
            "body_text": "A door stands open.",
            "label": "Step through",
            "target_page_id": "1",
            "weight": "",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with db.connect(db_path) as conn:
        page = conn.execute(
            "SELECT id, type FROM pages WHERE title = 'Open Door'"
        ).fetchone()
        assert page is not None
        options = conn.execute(
            "SELECT target_page_id, label, weight FROM options WHERE page_id = ?",
            (page["id"],),
        ).fetchall()
    assert len(options) == 1
    assert options[0]["label"] == "Step through"
    assert options[0]["target_page_id"] == 1
    assert options[0]["weight"] is None

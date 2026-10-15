"""Admin page form: the single-form options panel on create/edit.

The page create/edit form is the seam at which the operator sees and mutates
the page's outgoing options. On the edit form a single <form> carries the page
fields and one row per option, and one Save button persists the whole page:
the edit endpoint reconciles the submitted option rows (update, insert,
remove, reorder) atomically. The per-option CRUD endpoints still exist and
are pinned by ``test_admin_options.py``.

These tests pin the rendered HTML (one form, one Save, a Remove button per
row) and the observable result of a unified save through the HTTP seam. The
page-type specific rules (choice vs chance vs ending) are pinned by
``test_admin_options.py``.
"""

from pathlib import Path

from werkzeug.security import generate_password_hash

from adventurer import create_app, db

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct horse battery staple"


def test_edit_form_is_one_form_with_one_save_and_per_row_remove(
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

    # One <form> wraps the page fields and every option, so a single Save
    # button persists the whole page.
    assert html.count("<form") == 1
    assert html.count('type="submit"') == 1
    # Existing options render inline in that form, not as per-option forms.
    assert 'value="Step through"' in html
    assert 'value="1">Open Door' in html
    assert '<option value="2" selected>The End' in html
    # Each option row has a Remove button; adding a row is a client-side clone
    # so the same Save button persists it.
    assert ">Remove<" in html
    assert ">Add option<" in html
    assert "addOption" in html
    # The old per-option submit endpoints are gone from the page.
    assert "/options/" not in html


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


# ---------------------------------------------------------------------------
# Slice: weight field is only rendered when the page is a chance page.
#
# Choice pages must have NULL weights (ERR_CHOICE_WEIGHT), and ending pages
# never have an options panel at all. So only the chance page's options carry
# a weight. The edit form can drop the weight input entirely for choice
# pages (the type is known); the new form keeps the input but hides it until
# the operator picks "chance" in the type dropdown.
# ---------------------------------------------------------------------------


def test_edit_form_omits_weight_field_for_choice_page(
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
            "VALUES (1, 'choice', 'Crossroads', 'Two roads diverge.', 0)"
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

    # On a choice page the weight field is not part of the form: choice
    # options must have NULL weight (ERR_CHOICE_WEIGHT), so there's nothing
    # to edit. This pins both the inline edit and the add-option form.
    assert 'name="weight"' not in html
    assert "Weight" not in html


def test_edit_form_shows_weight_field_for_chance_page(
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
            "VALUES (1, 'chance', 'Coin Flip', 'Flip a coin.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'Heads', 'Heads.', 1)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, weight, position) "
            "VALUES (1, 2, 60, 0)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    html = client.get("/admin/pages/1/edit").get_data(as_text=True)

    # On a chance page the weight field is part of the form: each option
    # needs its weight to participate in the roll.
    assert 'name="weight"' in html
    assert "Weight" in html
    # The existing option's weight is rendered into the weight field.
    assert 'value="60"' in html


def test_new_form_hides_weight_until_chance_selected(tmp_path: Path, monkeypatch) -> None:
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

    # The new form's type is not known at render time, so the weight field
    # is rendered but hidden by default. A inline script toggles its
    # visibility when the operator picks "chance" in the type dropdown.
    assert 'name="weight"' in html
    assert "Weight" in html
    # The weight wrapper carries `hidden` so it's invisible until JS shows it.
    assert "hidden" in html
    # The script references both the type select and the weight wrapper so
    # the two stay in sync.
    assert 'select[name="type"]' in html


# ---------------------------------------------------------------------------
# Slice: target dropdown offers a "blank page" option.
#
# Operators regularly build options before the target page exists. Picking
# the blank entry tells the server to create a placeholder ending page and
# point the option at it; the operator can rename and edit the placeholder
# later. The blank entry is a sentinel in the dropdown (value="blank") so it
# can't be confused with a real page id.
# ---------------------------------------------------------------------------


def test_edit_form_target_dropdown_includes_blank_option(
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

    # Every target dropdown (inline edit + add option) offers a blank entry
    # the operator can pick to create a placeholder ending on submit.
    assert html.count('value="blank"') >= 2


def test_new_form_target_dropdown_includes_blank_option(
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

    html = client.get("/admin/pages/new").get_data(as_text=True)

    # The new form's initial-option target dropdown also offers the blank
    # entry so a page can be created with an option that points at a
    # placeholder target in the same POST.
    assert 'value="blank"' in html


def test_blank_target_on_new_page_creates_placeholder_ending(
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
            "target_page_id": "blank",
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
        # The placeholder ending page was created on the fly and the option
        # points at it. The placeholder is a recognizable ending page that
        # the operator can find and rename later.
        placeholder = conn.execute(
            "SELECT id, type, title, body_text FROM pages "
            "WHERE id = ? AND type = 'ending'",
            (options[0]["target_page_id"],),
        ).fetchone()
    assert len(options) == 1
    assert options[0]["target_page_id"] == placeholder["id"]
    assert placeholder["body_text"] == ""


def test_blank_target_on_add_option_creates_placeholder_ending(
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

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    client.post(
        "/admin/pages/1/options/new",
        data={"label": "Step through", "target_page_id": "blank", "weight": ""},
    )

    with db.connect(db_path) as conn:
        options = conn.execute(
            "SELECT target_page_id FROM options WHERE page_id = 1"
        ).fetchall()
        placeholder = conn.execute(
            "SELECT id, type, title, body_text FROM pages "
            "WHERE id = ? AND type = 'ending'",
            (options[0]["target_page_id"],),
        ).fetchone()
    assert placeholder is not None
    assert placeholder["body_text"] == ""


# ---------------------------------------------------------------------------
# Slice: weight is rendered as an HTML range slider.
#
# A slider makes chance weights easier to balance visually than a free-form
# number input. The min/max/step are pinned in the markup so the slider can
# only produce integer weights in [0, 100] (the schema's CHECK constraint).
# ---------------------------------------------------------------------------


def test_weight_field_is_a_range_slider_on_edit_form(tmp_path: Path, monkeypatch) -> None:
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
            "VALUES (1, 'chance', 'Coin Flip', 'Flip a coin.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'Heads', 'Heads.', 1)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, weight, position) "
            "VALUES (1, 2, 60, 0)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    html = client.get("/admin/pages/1/edit").get_data(as_text=True)

    # The weight input is a range slider with the schema's allowed bounds
    # and the integer step that matches the validation (ERR_WEIGHT_INTEGER).
    assert 'type="range"' in html
    assert 'min="0"' in html
    assert 'max="100"' in html
    assert 'name="weight"' in html


def test_weight_field_is_a_range_slider_on_new_form(tmp_path: Path, monkeypatch) -> None:
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

    # The new form's initial-option weight slider also carries the bounds.
    # The field is hidden until the operator picks "chance" (slice above),
    # but the bounds are part of the markup.
    assert 'type="range"' in html
    assert 'min="0"' in html
    assert 'max="100"' in html


# ---------------------------------------------------------------------------
# Slice: an "Add" button lets the operator attach extra options to a form.
#
# On the new page form, the initial option is just a starting point. JS clones
# that fieldset on click so the operator can attach several options to the new
# page in one POST; the server iterates the parallel ``label`` / ``target_page_id``
# / ``weight`` lists. On the edit page, the existing add-option form (which
# already posts one option at a time) is preserved, and the JS also lets the
# operator add several at once before submitting.
# ---------------------------------------------------------------------------


def test_new_form_has_add_button_that_clones_initial_option(
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

    html = client.get("/admin/pages/new").get_data(as_text=True)

    # The button is wired up by name and visible by its label so the operator
    # can find it next to the initial option. The script defines an
    # ``addInitialOption`` function (or equivalent) that clones the initial
    # option fieldset so the server receives a list of options on submit.
    assert ">Add option<" in html
    assert "addInitialOption" in html
    assert "cloneNode" in html


def test_new_form_with_multiple_options_creates_them_all(
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
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'Elsewhere', 'Somewhere else.', 1)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    # Submit the new form with two option slots, the way JS-cloned fields
    # arrive at the server (parallel label / target_page_id / weight lists).
    response = client.post(
        "/admin/pages/new",
        data={
            "title": "Crossroads",
            "type": "choice",
            "body_text": "Two roads diverge.",
            "label": ["Go left", "Go right"],
            "target_page_id": ["1", "2"],
            "weight": ["", ""],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with db.connect(db_path) as conn:
        page = conn.execute("SELECT id FROM pages WHERE title = 'Crossroads'").fetchone()
        assert page is not None
        rows = conn.execute(
            "SELECT label, target_page_id, weight, position FROM options "
            "WHERE page_id = ? ORDER BY position, id",
            (page["id"],),
        ).fetchall()
    assert len(rows) == 2
    assert [(row["label"], row["target_page_id"], row["weight"]) for row in rows] == [
        ("Go left", 1, None),
        ("Go right", 2, None),
    ]
    assert [row["position"] for row in rows] == [0, 1]


def test_edit_form_add_option_can_be_repeated(tmp_path: Path, monkeypatch) -> None:
    """The edit page's add-option form keeps working after the new form gets JS."""
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
            "VALUES (1, 'choice', 'Crossroads', 'Two roads diverge.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'The End', 'You have arrived.', 1)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    # POST twice: each call adds one option via the existing endpoint.
    client.post(
        "/admin/pages/1/options/new",
        data={"label": "Go left", "target_page_id": "2", "weight": ""},
    )
    client.post(
        "/admin/pages/1/options/new",
        data={"label": "Go right", "target_page_id": "2", "weight": ""},
    )

    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT label, position FROM options WHERE page_id = 1 ORDER BY position"
        ).fetchall()
    assert [row["label"] for row in rows] == ["Go left", "Go right"]


# ---------------------------------------------------------------------------
# Slice: one Save button persists the page and all its options.
#
# The edit form is a single <form> carrying the page fields and one option
# row per option. Submitting it posts the whole page (fields plus parallel
# ``option_id`` / ``label`` / ``target_page_id`` / ``weight`` lists) to the
# edit endpoint, which reconciles the option rows in one atomic save. These
# tests pin the observable result through the HTTP seam.
# ---------------------------------------------------------------------------


def test_edit_page_saves_page_and_existing_option_in_one_request(
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

    response = client.post(
        "/admin/pages/1/edit",
        data={
            "title": "Open Door Renamed",
            "type": "choice",
            "body_text": "A door stands wide open.",
            "option_id": "1",
            "label": "Walk through",
            "target_page_id": "2",
            "weight": "",
        },
    )
    assert response.status_code == 302

    with db.connect(db_path) as conn:
        page = conn.execute("SELECT title, body_text FROM pages WHERE id = 1").fetchone()
        option = conn.execute(
            "SELECT label, target_page_id FROM options WHERE id = 1"
        ).fetchone()
    # Both the page fields and the option are saved by the one request.
    assert (page["title"], page["body_text"]) == (
        "Open Door Renamed",
        "A door stands wide open.",
    )
    assert (option["label"], option["target_page_id"]) == ("Walk through", 2)


def test_edit_page_inserts_new_option_rows_in_order(tmp_path: Path, monkeypatch) -> None:
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
            "VALUES (1, 'choice', 'Crossroads', 'Two roads diverge.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'The End', 'You have arrived.', 1)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, position) "
            "VALUES (1, 2, 'Go left', 0)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    client.post(
        "/admin/pages/1/edit",
        data={
            "title": "Crossroads",
            "type": "choice",
            "body_text": "Two roads diverge.",
            "option_id": ["1", ""],
            "label": ["Go left", "Go right"],
            "target_page_id": ["2", "2"],
            "weight": ["", ""],
        },
    )

    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT label, position FROM options WHERE page_id = 1 ORDER BY position, id"
        ).fetchall()
    # The blank-id row is a new option; its position follows its row order.
    assert [(row["label"], row["position"]) for row in rows] == [
        ("Go left", 0),
        ("Go right", 1),
    ]


def test_edit_page_removes_options_omitted_from_the_form(
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
            "VALUES (1, 'choice', 'Crossroads', 'Two roads diverge.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'The End', 'You have arrived.', 1)"
        )
        conn.execute(
            "INSERT INTO options (id, page_id, target_page_id, label, position) "
            "VALUES (1, 1, 2, 'Go left', 0)"
        )
        conn.execute(
            "INSERT INTO options (id, page_id, target_page_id, label, position) "
            "VALUES (2, 1, 2, 'Go right', 1)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    # The operator's Remove button dropped option 1 from the form, so only
    # option 2 is submitted.
    client.post(
        "/admin/pages/1/edit",
        data={
            "title": "Crossroads",
            "type": "choice",
            "body_text": "Two roads diverge.",
            "option_id": ["2"],
            "label": ["Go right"],
            "target_page_id": ["2"],
            "weight": [""],
        },
    )

    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, label, position FROM options WHERE page_id = 1 "
            "ORDER BY position, id"
        ).fetchall()
    assert [(row["id"], row["label"], row["position"]) for row in rows] == [
        (2, "Go right", 0)
    ]


def test_edit_page_rejects_an_invalid_option_and_writes_nothing(
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

    response = client.post(
        "/admin/pages/1/edit",
        data={
            "title": "Renamed",
            "type": "choice",
            "body_text": "Changed.",
            "option_id": ["1"],
            "label": [""],
            "target_page_id": ["2"],
            "weight": [""],
        },
    )
    assert response.status_code == 200
    assert b"label is required" in response.data.lower()

    with db.connect(db_path) as conn:
        page = conn.execute("SELECT title, body_text FROM pages WHERE id = 1").fetchone()
        option = conn.execute("SELECT label FROM options WHERE page_id = 1").fetchone()
    # A rejected option rejects the whole save; the page is left untouched.
    assert (page["title"], page["body_text"]) == ("Open Door", "A door stands open.")
    assert option["label"] == "Step through"


def test_edit_page_saves_chance_weights_that_sum_to_100(
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
            "VALUES (1, 'chance', 'Coin Flip', 'Flip a coin.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'Heads', 'Heads.', 1)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (3, 'ending', 'Tails', 'Tails.', 2)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    client.post(
        "/admin/pages/1/edit",
        data={
            "title": "Coin Flip",
            "type": "chance",
            "body_text": "Flip a coin.",
            "option_id": ["", ""],
            "label": ["", ""],
            "target_page_id": ["2", "3"],
            "weight": ["60", "40"],
        },
    )

    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT target_page_id, weight, position FROM options "
            "WHERE page_id = 1 ORDER BY position, id"
        ).fetchall()
    assert [(row["target_page_id"], row["weight"], row["position"]) for row in rows] == [
        (2, 60, 0),
        (3, 40, 1),
    ]


def test_edit_page_rejects_chance_weights_that_do_not_sum_to_100(
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
            "VALUES (1, 'chance', 'Coin Flip', 'Flip a coin.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'ending', 'Heads', 'Heads.', 1)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    response = client.post(
        "/admin/pages/1/edit",
        data={
            "title": "Coin Flip",
            "type": "chance",
            "body_text": "Flip a coin.",
            "option_id": [""],
            "label": [""],
            "target_page_id": ["2"],
            "weight": ["60"],
        },
    )
    assert response.status_code == 200
    assert b"100" in response.data.lower()

    with db.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM options WHERE page_id = 1").fetchone()[
            0
        ]
    assert count == 0


def test_edit_page_drops_options_when_the_type_becomes_ending(
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

    # Changing the type to ending hides the options panel, so no option rows
    # are submitted; ending pages must end up with no options at all.
    response = client.post(
        "/admin/pages/1/edit",
        data={"title": "Open Door", "type": "ending", "body_text": "It ends."},
    )
    assert response.status_code == 302

    with db.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM options WHERE page_id = 1").fetchone()[
            0
        ]
    assert count == 0

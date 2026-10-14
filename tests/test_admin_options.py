"""Admin option-management seam: the option routes and their validation errors.

Pins the Issue #8 contract. Options belong to a page and are managed through
these routes (server-rendered Jinja, behind the admin login #6):

- add:    ``POST /admin/pages/<page_id>/options/new``
- edit:   ``POST /admin/pages/<page_id>/options/<option_id>/edit``
- delete: ``POST /admin/pages/<page_id>/options/<option_id>/delete``
- reorder:``POST /admin/pages/<page_id>/options/reorder`` (repeated
           ``option_id`` fields in the desired order)

Per-type rules:

- ``choice``: each option requires a non-empty ``label`` and a
  ``target_page_id``; ``weight`` must be NULL.
- ``chance``: each option requires a ``target_page_id`` and an integer
  ``weight`` in 0-100; the page's weights must sum to exactly 100.
- ``ending``: zero options; any add is rejected.

A rejected mutation leaves the database unchanged and renders a visible error.
The test seeds the admin credential and pages through the ``adventurer.db`` seam and
logs in before touching ``/admin/*``.
"""

from pathlib import Path
from typing import Any

from werkzeug.security import generate_password_hash

from adventurer import create_app, db

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct horse battery staple"


def _options(db_path: str, page_id: int) -> list[dict[str, Any]]:
    """Return a page's options as plain dicts, in position order."""
    with db.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, target_page_id, label, weight, position FROM options "
            "WHERE page_id = ? ORDER BY position, id",
            (page_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def test_admin_option_management_seam(tmp_path: Path, monkeypatch) -> None:
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
        # Page 1 is the choice page under management; pages 2 and 3 are its
        # targets. Page 4 is an empty chance page (targets 5, 6). Page 7 is an
        # ending page that must never gain options.
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (1, 'choice', 'Crossroads', 'Two roads diverge.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'choice', 'Left Path', 'A left path.', 1)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (3, 'ending', 'Right End', 'A right end.', 2)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (4, 'chance', 'Coin Flip', 'Flip a coin.', 3)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (5, 'ending', 'Heads', 'Heads.', 4)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (6, 'ending', 'Tails', 'Tails.', 5)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (7, 'ending', 'The End', 'Nothing follows.', 6)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (8, 'ending', 'Elsewhere', 'Somewhere else.', 7)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    # --- choice page: add / edit / delete ---------------------------------
    # Add a valid choice option: non-empty label + target, no weight. The
    # stored weight is NULL.
    client.post(
        "/admin/pages/1/options/new",
        data={"label": "Go left", "target_page_id": "2", "weight": ""},
    )
    rows = _options(db_path, 1)
    assert len(rows) == 1
    first = rows[0]
    assert (first["label"], first["target_page_id"], first["weight"]) == (
        "Go left",
        2,
        None,
    )
    assert first["position"] == 0

    # Add a second option so ordering is observable.
    client.post(
        "/admin/pages/1/options/new",
        data={"label": "Go right", "target_page_id": "3", "weight": ""},
    )
    rows = _options(db_path, 1)
    assert [row["label"] for row in rows] == ["Go left", "Go right"]
    assert [row["position"] for row in rows] == [0, 1]
    second = rows[1]

    # Edit: label and target change, weight stays NULL.
    client.post(
        f"/admin/pages/1/options/{first['id']}/edit",
        data={"label": "Go left (renamed)", "target_page_id": "3", "weight": ""},
    )
    edited = _options(db_path, 1)[0]
    assert (edited["label"], edited["target_page_id"], edited["weight"]) == (
        "Go left (renamed)",
        3,
        None,
    )

    # Reordering persists ``position`` and is reflected by the player API.
    reordered = client.post(
        "/admin/pages/1/options/reorder",
        data={"option_id": [str(second["id"]), str(first["id"])]},
    )
    assert reordered.status_code in (200, 302)
    after = _options(db_path, 1)
    assert [row["id"] for row in after] == [second["id"], first["id"]]
    assert [row["position"] for row in after] == [0, 1]
    page_json = client.get("/api/pages/1").get_json()
    assert [option["label"] for option in page_json["options"]] == [
        "Go right",
        "Go left (renamed)",
    ]

    # Delete removes the option.
    client.post(f"/admin/pages/1/options/{second['id']}/delete")
    assert [row["label"] for row in _options(db_path, 1)] == ["Go left (renamed)"]

    # --- choice page validation -------------------------------------------
    # Empty label is rejected and nothing is written.
    before = _options(db_path, 1)
    empty_label = client.post(
        "/admin/pages/1/options/new",
        data={"label": "", "target_page_id": "2", "weight": ""},
    )
    assert _options(db_path, 1) == before
    assert b"label" in empty_label.data.lower()

    # A missing target_page_id is rejected.
    before = _options(db_path, 1)
    missing_target = client.post(
        "/admin/pages/1/options/new",
        data={"label": "Nowhere", "target_page_id": "", "weight": ""},
    )
    assert _options(db_path, 1) == before
    assert b"target" in missing_target.data.lower()

    # A choice option must not carry a weight (weight stays NULL).
    before = _options(db_path, 1)
    weighted_choice = client.post(
        "/admin/pages/1/options/new",
        data={"label": "Weighted", "target_page_id": "2", "weight": "50"},
    )
    assert _options(db_path, 1) == before
    assert b"weight" in weighted_choice.data.lower()

    # --- chance page: per-type weight validation --------------------------
    # A chance page's weights must sum to exactly 100. A lone weight of 50 is
    # rejected ...
    rejected_sum = client.post(
        "/admin/pages/4/options/new",
        data={"label": "heads", "target_page_id": "5", "weight": "50"},
    )
    assert _options(db_path, 4) == []
    assert b"100" in rejected_sum.data.lower()

    # ... while a 100-weight option is accepted, and a 0-weight option keeps
    # the total at 100.
    client.post(
        "/admin/pages/4/options/new",
        data={"label": "heads", "target_page_id": "5", "weight": "100"},
    )
    client.post(
        "/admin/pages/4/options/new",
        data={"label": "tails", "target_page_id": "6", "weight": "0"},
    )
    chance_rows = _options(db_path, 4)
    assert [row["weight"] for row in chance_rows] == [100, 0]
    assert sum(row["weight"] for row in chance_rows) == 100
    hundred = chance_rows[0]

    # Editing a weight so the total is no longer 100 is rejected.
    before = _options(db_path, 4)
    rejected_edit = client.post(
        f"/admin/pages/4/options/{hundred['id']}/edit",
        data={"label": "heads", "target_page_id": "5", "weight": "50"},
    )
    assert _options(db_path, 4) == before
    assert b"100" in rejected_edit.data.lower()

    # A weight outside 0-100 is rejected.
    before = _options(db_path, 4)
    out_of_range = client.post(
        "/admin/pages/4/options/new",
        data={"label": "huge", "target_page_id": "5", "weight": "150"},
    )
    assert _options(db_path, 4) == before
    assert b"weight" in out_of_range.data.lower()

    # A non-integer weight is rejected.
    before = _options(db_path, 4)
    non_integer = client.post(
        "/admin/pages/4/options/new",
        data={"label": "fraction", "target_page_id": "5", "weight": "3.5"},
    )
    assert _options(db_path, 4) == before
    assert b"weight" in non_integer.data.lower()

    # A chance option requires a target_page_id.
    before = _options(db_path, 4)
    chance_missing_target = client.post(
        "/admin/pages/4/options/new",
        data={"label": "nowhere", "target_page_id": "", "weight": "0"},
    )
    assert _options(db_path, 4) == before
    assert b"target" in chance_missing_target.data.lower()

    # --- ending page: options are forbidden -------------------------------
    before = _options(db_path, 7)
    rejected_ending = client.post(
        "/admin/pages/7/options/new",
        data={"label": "nope", "target_page_id": "8", "weight": ""},
    )
    assert before == []
    assert _options(db_path, 7) == []
    assert b"ending" in rejected_ending.data.lower()

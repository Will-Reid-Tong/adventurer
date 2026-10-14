"""Tests for the raw-SQL data layer seam: ``adventurer.db.init_db`` and ``adventurer.db.connect``.

These pin the Issue #2 acceptance criteria: idempotent schema application and
constraint enforcement (CHECK, ON DELETE CASCADE, ON DELETE SET NULL).
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest


def test_data_layer_seam(tmp_path: Path) -> None:
    assert importlib.util.find_spec("adventurer.db") is not None, (
        "adventurer.db seam module is not implemented yet"
    )
    from adventurer import db

    db_path = str(tmp_path / "app.db")

    # init_db applies schema.sql and is idempotent.
    db.init_db(db_path)
    db.init_db(db_path)

    with db.connect(db_path) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {"settings", "images", "pages", "options"} <= tables

    # pages.type CHECK rejects an invalid value.
    with pytest.raises(sqlite3.IntegrityError), db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO pages (type, title, body_text) VALUES (?, ?, ?)",
            ("bogus", "Title", "Body"),
        )

    # Seed two valid pages so option foreign keys resolve.
    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) VALUES (1, 'chance', 'A', 'A')"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) VALUES (2, 'ending', 'B', 'B')"
        )

    # options.weight CHECK rejects values outside 0-100.
    for bad_weight in (-1, 101):
        with pytest.raises(sqlite3.IntegrityError), db.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO options (page_id, target_page_id, weight) VALUES (1, 2, ?)",
                (bad_weight,),
            )

    # Deleting a page cascades to delete its options.
    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, weight) VALUES (1, 2, 50)"
        )
    with db.connect(db_path) as conn:
        conn.execute("DELETE FROM pages WHERE id = 1")
    with db.connect(db_path) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM options").fetchone()[0]
    assert remaining == 0

    # Deleting an image sets the referencing page's image_id to NULL.
    with db.connect(db_path) as conn:
        image_id = conn.execute(
            "INSERT INTO images (filename, content_type, data) VALUES (?, ?, ?)",
            ("cat.png", "image/png", b"\x89PNG\r\n"),
        ).lastrowid
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, image_id) VALUES (3, 'ending', 'C', 'C', ?)",
            (image_id,),
        )
    with db.connect(db_path) as conn:
        conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
    with db.connect(db_path) as conn:
        image_id_after = conn.execute(
            "SELECT image_id FROM pages WHERE id = 3"
        ).fetchone()["image_id"]
    assert image_id_after is None

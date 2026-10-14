"""Player API seam: ``GET /api/start`` and ``GET /api/pages/<id>``.

Pins the Issue #3 JSON contract the player frontend consumes:

- start page id from ``settings.start_page_id`` (or ``null``);
- choice pages expose ``options`` with ``label`` and ``target_page_id``;
- ending pages expose ``options == []``;
- chance pages omit ``options`` entirely (the client never sees weights);
- unknown ids return 404.
"""

from pathlib import Path

from adventurer import create_app, db


def test_player_api_page_json_seam(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "app.db")
    db.init_db(db_path)

    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO images (id, filename, content_type, data) VALUES (?, ?, ?, ?)",
            (1, "cover.png", "image/png", b"\x89PNG\r\n"),
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, image_id) "
            "VALUES (1, 'choice', 'Start', 'You are at the start.', 1)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) "
            "VALUES (2, 'ending', 'The End', 'You win.')"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) "
            "VALUES (3, 'chance', 'Gamble', 'Roll the dice.')"
        )
        conn.execute(
            "INSERT INTO options (id, page_id, target_page_id, label) "
            "VALUES (1, 1, 2, 'Go forward')"
        )
        conn.execute(
            "INSERT INTO options (id, page_id, target_page_id, label, weight) "
            "VALUES (2, 3, 2, 'win', 100)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()

    # Unset start page -> explicit null.
    response = client.get("/api/start")
    assert response.status_code == 200
    assert response.get_json() == {"page_id": None}

    with db.connect(db_path) as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('start_page_id', '1')")

    # Configured start page -> its id.
    response = client.get("/api/start")
    assert response.status_code == 200
    assert response.get_json() == {"page_id": 1}

    # Choice page -> its options, plus the image contract.
    response = client.get("/api/pages/1")
    assert response.status_code == 200
    assert response.get_json() == {
        "id": 1,
        "type": "choice",
        "title": "Start",
        "body_text": "You are at the start.",
        "image_url": "/images/1",
        "options": [{"id": 1, "label": "Go forward", "target_page_id": 2}],
    }

    # Ending page -> options is exactly [].
    response = client.get("/api/pages/2")
    assert response.status_code == 200
    ending = response.get_json()
    assert ending["type"] == "ending"
    assert ending["options"] == []
    assert ending["image_url"] is None

    # Chance page -> options omitted entirely.
    response = client.get("/api/pages/3")
    assert response.status_code == 200
    chance = response.get_json()
    assert chance["type"] == "chance"
    assert "options" not in chance

    # Unknown page id -> 404.
    response = client.get("/api/pages/9999")
    assert response.status_code == 404

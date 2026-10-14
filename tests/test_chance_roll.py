"""Player API seam: seeded chance roll.

Pins the Issue #4 contract:

- the pure ``roll(options, rng)`` picks a target deterministically from a seeded
  ``random.Random`` (expected values below come from the stdlib ``random.choices``)
  and honours the weights over a large sample;
- ``POST /api/pages/<id>/roll`` returns ``200 {"page_id": <next>}`` for chance
  pages, ``400`` for choice/ending pages, and ``404`` for unknown ids;
- the ``random.Random`` is injected through app config so the draw is seedable.
"""

import random
from collections import Counter
from pathlib import Path

import pytest

from adventurer import create_app, db


def test_seeded_chance_roll_seam(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "app.db")
    db.init_db(db_path)

    with db.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) "
            "VALUES (1, 'chance', 'Gamble', 'Roll the dice.')"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) "
            "VALUES (2, 'ending', 'Win', 'You win.')"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) "
            "VALUES (3, 'ending', 'Lose', 'You lose.')"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) "
            "VALUES (4, 'choice', 'Choose', 'Pick a door.')"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text) "
            "VALUES (5, 'ending', 'Door', 'A quiet room.')"
        )
        # Chance page 1: 70% -> page 2, 30% -> page 3.
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, weight, position) "
            "VALUES (1, 2, 'win', 70, 0)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, weight, position) "
            "VALUES (1, 3, 'lose', 30, 1)"
        )
        # A choice page still has a target; it must not be rollable.
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, position) "
            "VALUES (4, 5, 'go', 0)"
        )

    monkeypatch.setenv("DATABASE_PATH", db_path)
    app = create_app()
    app.config["RNG"] = random.Random(1234)
    client = app.test_client()

    # Chance page -> 200 and the seeded next page id (seed 1234 picks page 3).
    response = client.post("/api/pages/1/roll")
    assert response.status_code == 200
    assert response.get_json() == {"page_id": 3}

    # Choice and ending pages -> 400.
    assert client.post("/api/pages/4/roll").status_code == 400
    assert client.post("/api/pages/2/roll").status_code == 400

    # Unknown page -> 404.
    assert client.post("/api/pages/9999/roll").status_code == 404

    # Pure function: same seed, same target.
    from adventurer.player import roll

    options = [(2, 70), (3, 30)]
    assert roll(options, random.Random(1234)) == 3

    # Pure function: a large seeded sample tracks the weights (~70/30).
    sample_rng = random.Random(2024)
    counts = Counter(roll(options, sample_rng) for _ in range(5000))
    assert counts[2] / 5000 == pytest.approx(0.70, abs=0.05)
    assert counts[3] / 5000 == pytest.approx(0.30, abs=0.05)

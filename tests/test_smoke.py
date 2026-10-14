"""Adventure frontend seam: ``GET /`` serves the single-page player app.

Pins the Issue #11 contract:

- ``GET /`` returns the player HTML (200, ``text/html``);
- the served page wires vanilla JS to the API contract (``/api/start``,
  ``/api/pages/<id>``, ``POST /api/pages/<id>/roll``);
- no JS framework or build step is introduced.
"""

from pathlib import Path

from cyoa import create_app

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_get_root_serves_player_app_at_api_seam():
    client = create_app().test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert response.mimetype == "text/html"

    # The client must drive the same API surface the player endpoints expose.
    html = response.get_data(as_text=True)
    assert "/api/start" in html
    assert "/api/pages/" in html
    assert "/roll" in html

    # Vanilla JS only: no framework and no build step.
    assert not (REPO_ROOT / "package.json").exists()

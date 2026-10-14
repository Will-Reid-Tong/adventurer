"""Admin graph-map seam: the pure ``build_graph()`` and its ``/admin/map`` renderer.

Pins the Issue #10 acceptance criteria:

- ``build_graph(conn)`` derives everything from the existing schema (no new
  tables or columns) — nodes from ``pages``, edges from ``options``, root from
  ``settings.start_page_id`` — and returns
  ``{"root": int | None,
     "nodes": [{"id", "type", "title", "image_id", "depth"}, ...],
     "edges": [{"page_id", "target_page_id", "label", "weight", "reentrant"},
               ...]}``.
- BFS from the root assigns each node a depth, so the start page is at the top
  and its successors below it.
- A **diamond** (two paths merging into one node) yields two edges into that
  node.
- A **cycle** pins the revisited page at its shallowest depth and marks the
  edge that points back up as ``reentrant`` (the renderer draws it dashed).
- ``/admin/map`` is a thin renderer over that structure: each node is an
  ``<a href="/admin/pages/<id>/edit">`` card, ordered by depth; choice edges
  show the option label and chance edges show the weight as ``40%``.
- The route sits behind the admin login (#6), so the test seeds
  ``admin_username`` / ``admin_password_hash`` through the ``adventurer.db`` seam and
  logs in before touching ``/admin/map``.

The fixture graph (root = page 1)::

    1 Start (choice) ──"Left"──▶ 2 Left (choice) ──"Merge"──▶ 4 Merge (ending)
        │                                                        ▲
        └──────"Right"────▶ 3 Right (chance) ──40%───────────────┘
                                  │
                                  └──60%──▶ 1   (cycle back to the root)

Page 4 is a merge (edges from 2 and 3); edge 3 -> 1 is the re-entrant one.
"""

from pathlib import Path
from urllib.parse import urlsplit

from werkzeug.security import generate_password_hash
from werkzeug.test import TestResponse

from adventurer import create_app, db

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct horse battery staple"


def _redirects_to_login(response: TestResponse) -> bool:
    """True when ``response`` is a 302 pointing at the login page."""
    return (
        response.status_code == 302
        and urlsplit(response.headers["Location"]).path == "/login"
    )


def _edit_link(page_id: int) -> bytes:
    """The exact anchor fragment the renderer must emit for ``page_id``."""
    return f'href="/admin/pages/{page_id}/edit"'.encode()


def _table_names(conn) -> set[str]:
    """The tables currently present in the database."""
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _seed_graph(db_path: str) -> None:
    """Write the diamond-plus-cycle fixture through the ``adventurer.db`` seam."""
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
            "VALUES (1, 'choice', 'Start', 'Two ways out.', 0)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (2, 'choice', 'Left', 'A left turn.', 1)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (3, 'chance', 'Right', 'Roll for the right turn.', 2)"
        )
        conn.execute(
            "INSERT INTO pages (id, type, title, body_text, position) "
            "VALUES (4, 'ending', 'Merge', 'Both paths meet here.', 3)"
        )
        # Choice edges carry a label and no weight.
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, position) "
            "VALUES (1, 2, 'Left', 0)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, position) "
            "VALUES (1, 3, 'Right', 1)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, position) "
            "VALUES (2, 4, 'Merge', 0)"
        )
        # Chance edges carry a weight summing to 100; the second is the cycle.
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, weight, position) "
            "VALUES (3, 4, NULL, 40, 0)"
        )
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, weight, position) "
            "VALUES (3, 1, NULL, 60, 1)"
        )


def test_admin_graph_map_seam(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "app.db")
    _seed_graph(db_path)

    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()

    # Guarded like every /admin/* route: unauthenticated -> login page.
    assert _redirects_to_login(client.get("/admin/map"))

    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    # --- /admin/map is a thin renderer over build_graph() -----------------
    response = client.get("/admin/map")
    assert response.status_code == 200

    # Every page is a card wrapped in a link to its editor.
    for page_id in (1, 2, 3, 4):
        assert _edit_link(page_id) in response.data

    # Vertical layout: the start page is at the top, its successors below it,
    # and the merge below both of its predecessors.
    order = [response.data.index(_edit_link(page_id)) for page_id in (1, 2, 3, 4)]
    assert order[0] < order[1] < order[3]
    assert order[0] < order[2] < order[3]

    # Edge labels: choice edges show their label, chance edges show the weight
    # as a percentage.
    assert b"Left" in response.data
    assert b"Right" in response.data
    assert b"Merge" in response.data
    assert b"40%" in response.data
    assert b"60%" in response.data

    # --- the pure build_graph() seam --------------------------------------
    from adventurer.graph import build_graph

    with db.connect(db_path) as conn:
        tables_before = _table_names(conn)
        graph = build_graph(conn)
        tables_after = _table_names(conn)

    # Derived from existing data only: no new tables were created.
    assert tables_after == tables_before

    assert graph["root"] == 1

    nodes = {node["id"]: node for node in graph["nodes"]}
    assert set(nodes) == {1, 2, 3, 4}

    # BFS depth layout from the root.
    assert nodes[1]["depth"] == 0
    assert nodes[2]["depth"] == 1
    assert nodes[3]["depth"] == 1
    assert nodes[4]["depth"] == 2

    edges = graph["edges"]
    assert len(edges) == 5

    # Diamond (merge): both 2 and 3 feed page 4.
    into_merge = [edge for edge in edges if edge["target_page_id"] == 4]
    assert {(edge["page_id"], edge["label"], edge["weight"]) for edge in into_merge} == {
        (2, "Merge", None),
        (3, None, 40),
    }

    # Cycle: the edge back to the root is marked re-entrant, and the root stays
    # pinned at its shallowest depth rather than being pushed deeper.
    back_edges = [
        edge for edge in edges if edge["page_id"] == 3 and edge["target_page_id"] == 1
    ]
    assert len(back_edges) == 1
    assert back_edges[0]["reentrant"] is True
    assert back_edges[0]["weight"] == 60
    assert nodes[1]["depth"] == 0

    # Forward edges are not marked re-entrant.
    forward = [edge for edge in edges if edge not in back_edges]
    assert all(edge["reentrant"] is False for edge in forward)

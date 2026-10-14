"""Pure derivation of the branch map from the existing schema.

No new tables or columns: nodes come from ``pages``, edges from ``options``,
and the root from ``settings.start_page_id``.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from typing import Any

from cyoa.db import get_start_page_id

# Fixed card metrics for the vertical HTML map. The renderer sizes its cards
# and connector endpoints from these so the SVG lines land on the cards.
CARD_WIDTH = 200
CARD_HEIGHT = 72
COLUMN_GAP = 40
ROW_GAP = 64


def build_graph(conn: sqlite3.Connection) -> dict[str, Any]:
    """Return ``{root, nodes, edges}`` with a BFS depth per page.

    Reachable nodes get their BFS depth (start page at 0). Nodes that cannot be
    reached from the root get a depth after every reachable node, so the start
    page is unambiguously at the top. ``edges`` carry a ``reentrant`` flag for
    links that point back up to an already-seen shallower node (cycles/merges
    drawn dashed by the renderer).
    """
    pages = conn.execute("SELECT id, type, title, image_id FROM pages").fetchall()
    options = conn.execute(
        "SELECT page_id, target_page_id, label, weight FROM options"
    ).fetchall()
    root = get_start_page_id(conn)

    outgoing: dict[int, list[int]] = {}
    for option in options:
        outgoing.setdefault(option["page_id"], []).append(option["target_page_id"])

    depths: dict[int, int] = {}
    if root is not None:
        depths[root] = 0
        queue: deque[int] = deque([root])
        while queue:
            page_id = queue.popleft()
            for target in outgoing.get(page_id, []):
                if target not in depths:
                    depths[target] = depths[page_id] + 1
                    queue.append(target)

    # Unreachable pages sit in a row after the reachable graph rather than
    # sharing depth 0 with the start page.
    orphan_depth = max(depths.values(), default=-1) + 1

    nodes = [
        {
            "id": page["id"],
            "type": page["type"],
            "title": page["title"],
            "image_id": page["image_id"],
            "depth": depths.get(page["id"], orphan_depth),
        }
        for page in pages
    ]
    edges = [
        {
            "page_id": option["page_id"],
            "target_page_id": option["target_page_id"],
            "label": option["label"],
            "weight": option["weight"],
            "reentrant": option["target_page_id"] in depths
            and depths[option["target_page_id"]]
            <= depths.get(option["page_id"], orphan_depth),
        }
        for option in options
    ]
    return {"root": root, "nodes": nodes, "edges": edges}


def layout_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Compute absolute positions for the vertical HTML map.

    Cards are laid out top-down by ``depth`` and left-to-right by ``id``.
    Returned edges carry box-relative endpoint coordinates so the renderer can
    draw connectors *behind* the HTML cards; re-entrant edges simply run
    upward from their source to their target.
    """
    nodes = sorted(graph["nodes"], key=lambda node: (node["depth"], node["id"]))
    rows: dict[int, list[dict[str, Any]]] = {}
    for node in nodes:
        rows.setdefault(node["depth"], []).append(dict(node))

    positions: dict[int, tuple[float, float]] = {}
    laid_nodes: list[dict[str, Any]] = []
    widest = 0
    for depth in sorted(rows):
        row = rows[depth]
        widest = max(widest, len(row))
        for column, node in enumerate(row):
            x = column * (CARD_WIDTH + COLUMN_GAP)
            y = depth * (CARD_HEIGHT + ROW_GAP)
            positions[node["id"]] = (x, y)
            laid_nodes.append({**node, "x": x, "y": y})

    edges = []
    for edge in graph["edges"]:
        source_x, source_y = positions.get(edge["page_id"], (0.0, 0.0))
        target_x, target_y = positions.get(edge["target_page_id"], (0.0, 0.0))
        edges.append(
            {
                **edge,
                "x1": source_x + CARD_WIDTH / 2,
                "y1": source_y + CARD_HEIGHT,
                "x2": target_x + CARD_WIDTH / 2,
                "y2": target_y,
            }
        )

    width = max(widest, 1) * (CARD_WIDTH + COLUMN_GAP) - COLUMN_GAP
    height = (max(rows) + 1 if rows else 1) * (CARD_HEIGHT + ROW_GAP) - ROW_GAP
    return {
        "nodes": laid_nodes,
        "edges": edges,
        "width": width,
        "height": height,
        "card_width": CARD_WIDTH,
        "card_height": CARD_HEIGHT,
    }

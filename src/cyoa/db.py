"""Raw-SQL SQLite data layer: schema application and connection helpers."""

from __future__ import annotations

import os
import sqlite3
from importlib import resources
from typing import cast

from flask import Flask, current_app, g

DEFAULT_DATABASE_PATH = "data/app.db"


def connect(path: str) -> sqlite3.Connection:
    """Open a connection with named-row access and foreign keys enforced."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str) -> None:
    """Apply ``schema.sql`` to the database at ``path``, idempotently."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    schema = resources.files("cyoa").joinpath("schema.sql").read_text(encoding="utf-8")
    conn = connect(path)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()


def get_db() -> sqlite3.Connection:
    """Return the per-request connection, opening it on first use."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return cast(sqlite3.Connection, g.db)


def close_db(exc: BaseException | None = None) -> None:
    """Close the per-request connection, if one was opened."""
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    """Return the stored value for ``key``, or ``None`` when unset."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row["value"])


def get_start_page_id(conn: sqlite3.Connection) -> int | None:
    """Return the configured ``start_page_id``, or ``None`` when unset."""
    value = get_setting(conn, "start_page_id")
    return None if value is None else int(value)


def database_path() -> str:
    """Resolve the database path from ``DATABASE_PATH`` with a dev default."""
    return os.environ.get("DATABASE_PATH", DEFAULT_DATABASE_PATH)


def init_app(app: Flask) -> None:
    """Wire the data layer into ``app``: config default and teardown."""
    app.config.setdefault("DATABASE_PATH", database_path())
    app.teardown_appcontext(close_db)

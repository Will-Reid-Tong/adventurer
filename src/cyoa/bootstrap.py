"""First-run bootstrap of the single admin credential.

A fresh database has no login, so this seeds the one setting that cannot be
derived from existing data. ``ADMIN_USERNAME`` and ``ADMIN_PASSWORD`` are read
from the environment with documented development defaults, and values are only
written when missing so a configured credential is never overwritten.
"""

from __future__ import annotations

import os

from werkzeug.security import generate_password_hash

from cyoa import db

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin"


def bootstrap_admin(path: str | None = None) -> None:
    """Seed ``admin_username`` / ``admin_password_hash`` if the database lacks them."""
    username = os.environ.get("ADMIN_USERNAME") or DEFAULT_ADMIN_USERNAME
    password = os.environ.get("ADMIN_PASSWORD") or DEFAULT_ADMIN_PASSWORD
    conn = db.connect(path or db.database_path())
    try:
        if db.get_setting(conn, "admin_username") is None:
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('admin_username', ?)",
                (username,),
            )
        if db.get_setting(conn, "admin_password_hash") is None:
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) "
                "VALUES ('admin_password_hash', ?)",
                (generate_password_hash(password),),
            )
        conn.commit()
    finally:
        conn.close()

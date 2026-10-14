#!/bin/sh
# Initialize the SQLite schema before gunicorn starts, then seed the admin
# credential on first run. Both steps are idempotent, so this is safe on every
# start, including a freshly mounted /data volume.
#
# ADMIN_USERNAME / ADMIN_PASSWORD configure the first-run login; they default to
# "admin" / "admin" for development (see README.md).
set -eu

python - <<'PY'
import os

from adventurer import db
from adventurer.bootstrap import bootstrap_admin

path = os.environ.get("DATABASE_PATH", "/data/app.db")
db.init_db(path)
bootstrap_admin(path)
PY

exec "$@"

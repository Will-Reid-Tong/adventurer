import os
import random
import sqlite3
from typing import Any

from flask import (
    Flask,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.datastructures import FileStorage
from werkzeug.security import check_password_hash, generate_password_hash

from adventurer import db, player
from adventurer.bootstrap import bootstrap_admin
from adventurer.constants import (
    ALLOWED_IMAGE_TYPES,
    ALLOWED_PAGE_TYPES,
    BLANK_PAGE_TITLE,
    BLANK_TARGET,
    ERR_CHOICE_WEIGHT,
    ERR_ENDING_OPTIONS,
    ERR_IMAGE_REQUIRED,
    ERR_IMAGE_SIZE,
    ERR_IMAGE_TYPE,
    ERR_INVALID_PAGE_TYPE,
    ERR_LABEL_REQUIRED,
    ERR_TARGET_INTEGER,
    ERR_TARGET_REQUIRED,
    ERR_WEIGHT_INTEGER,
    ERR_WEIGHT_RANGE,
    ERR_WEIGHT_REQUIRED,
    ERR_WEIGHT_SUM,
    IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    MAX_WEIGHT,
    MIN_WEIGHT,
    PAGE_TYPES,
    WEIGHT_TOTAL,
)
from adventurer.graph import build_graph, layout_graph


class ImageUploadError(Exception):
    """A rejected admin image upload, carrying the matching HTTP status."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _read_image(file: FileStorage) -> tuple[str, str, bytes]:
    """Validate an uploaded image, returning ``(filename, content_type, data)``."""
    if file.filename is None or file.filename == "":
        raise ImageUploadError(ERR_IMAGE_REQUIRED, 400)
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise ImageUploadError(ERR_IMAGE_TYPE, 400)
    data = bytes(file.read())
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageUploadError(ERR_IMAGE_SIZE, 413)
    return str(file.filename), str(file.content_type), data


def _insert_image(conn: sqlite3.Connection, file: FileStorage) -> int:
    """Validate and insert an image row, returning its id.

    Replacing a page's image goes through here too: it inserts a new row; the
    page's ``image_id`` is repointed by the caller and the old row is left for
    later garbage collection (Issue #5).
    """
    filename, content_type, data = _read_image(file)
    cursor = conn.execute(
        "INSERT INTO images (filename, content_type, data) VALUES (?, ?, ?)",
        (filename, content_type, data),
    )
    return int(cursor.lastrowid or 0)


def _is_upload(file: FileStorage | None) -> bool:
    """True when a non-empty file was submitted."""
    return file is not None and file.filename is not None and file.filename != ""


def _resolve_target_page_id(conn: sqlite3.Connection, raw: str) -> int:
    """Resolve a target_page_id form value to an integer page id.

    The blank sentinel (``"blank"``) creates a placeholder ending page and
    returns its id. Any other value is parsed as an integer; the caller
    handles the case where the id does not exist.
    """
    if raw == BLANK_TARGET:
        cursor = conn.execute(
            "INSERT INTO pages (type, title, body_text, position) "
            "VALUES ('ending', ?, '', ?)",
            (
                BLANK_PAGE_TITLE,
                conn.execute(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM pages"
                ).fetchone()[0],
            ),
        )
        return int(cursor.lastrowid or 0)
    return int(raw)


def _create_initial_options(
    conn: sqlite3.Connection,
    page_id: int,
    page_type: str,
    form: Any,
) -> None:
    """Create one option per parallel ``label`` / ``target_page_id`` / ``weight`` slot.

    The new-page form lets the operator attach any number of options by
    cloning the initial-option fieldset on the client (so each slot
    contributes parallel list values to the POST). Slots with an empty
    ``target_page_id`` are skipped silently — they're unfilled fieldsets.
    Invalid slots are skipped too, so the page itself is still created when
    one slot is rejected.
    """
    labels = form.getlist("label")
    targets = form.getlist("target_page_id")
    weights = form.getlist("weight")
    slot_count = max(len(labels), len(targets), len(weights), 1)
    existing_sum = 0
    position = 0
    for index in range(slot_count):
        label = labels[index] if index < len(labels) else ""
        target_raw = (targets[index] if index < len(targets) else "").strip()
        weight_raw = (weights[index] if index < len(weights) else "").strip()
        if not target_raw:
            continue
        slot_form: dict[str, str] = {
            "label": label,
            "target_page_id": target_raw,
            "weight": weight_raw,
        }
        values, _error = _parse_option(
            conn, page_type, slot_form, existing_sum=existing_sum
        )
        if values is None:
            continue
        existing_sum += values["weight"] or 0
        conn.execute(
            "INSERT INTO options "
            "(page_id, target_page_id, label, weight, position) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                page_id,
                values["target_page_id"],
                values["label"],
                values["weight"],
                position,
            ),
        )
        position += 1


def _render_page_form(
    page: Any,
    error: str | None,
    *,
    options: list[Any] | None = None,
    pages: list[Any] | None = None,
    status: int = 200,
) -> tuple[str, int]:
    """Render the page create/edit form with the shared type/format constants.

    ``pages`` powers the target dropdown in the options panel; ``options`` is
    the current page's existing options, used to render inline edit forms on
    the edit page.
    """
    return (
        render_template(
            "admin/page_form.html",
            page=page,
            error=error,
            page_types=PAGE_TYPES,
            image_types=IMAGE_TYPES,
            options=options or [],
            pages=pages or [],
        ),
        status,
    )


def _parse_option_values(
    conn: sqlite3.Connection, page_type: str, form: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate one option's own fields for ``page_type``.

    This checks everything local to the option (target, label, weight range)
    but not the chance page's weights-sum-to-100 rule, which is page-level and
    therefore checked by the caller. ``conn`` is used to materialise a
    placeholder page when the form picks the blank-target sentinel.
    """
    if page_type == "ending":
        return None, ERR_ENDING_OPTIONS
    label = form.get("label", "")
    target_raw = (form.get("target_page_id") or "").strip()
    weight_raw = (form.get("weight") or "").strip()
    if not target_raw:
        return None, ERR_TARGET_REQUIRED
    try:
        target_page_id = _resolve_target_page_id(conn, target_raw)
    except ValueError:
        return None, ERR_TARGET_INTEGER
    if page_type == "choice":
        if not label.strip():
            return None, ERR_LABEL_REQUIRED
        if weight_raw:
            return None, ERR_CHOICE_WEIGHT
        return {
            "label": label,
            "target_page_id": target_page_id,
            "weight": None,
        }, None
    if not weight_raw:
        return None, ERR_WEIGHT_REQUIRED
    try:
        weight = int(weight_raw)
    except ValueError:
        return None, ERR_WEIGHT_INTEGER
    if weight < MIN_WEIGHT or weight > MAX_WEIGHT:
        return None, ERR_WEIGHT_RANGE
    return {
        "label": label,
        "target_page_id": target_page_id,
        "weight": weight,
    }, None


def _parse_option(
    conn: sqlite3.Connection,
    page_type: str,
    form: Any,
    *,
    existing_sum: int = 0,
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate an option form for ``page_type``; return ``(values, error)``.

    ``existing_sum`` is the sum of the page's other options' weights, used to
    enforce the chance page's weights-sum-to-100 rule.
    """
    values, error = _parse_option_values(conn, page_type, form)
    if values is None:
        return None, error
    if page_type == "chance" and existing_sum + values["weight"] != WEIGHT_TOTAL:
        return None, ERR_WEIGHT_SUM
    return values, None


def _parse_submitted_options(
    conn: sqlite3.Connection, page_type: str, form: Any
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """Parse the page form's parallel option lists into ordered row dicts.

    Each row is ``{"id": option_id | None, "values": {...}}``; an existing
    option carries its id, a new row does not. A row with neither an id nor a
    target is a blank new row and is dropped. Returns ``(None, error)`` on the
    first invalid row.
    """
    option_ids = form.getlist("option_id")
    labels = form.getlist("label")
    targets = form.getlist("target_page_id")
    weights = form.getlist("weight")
    slot_count = max(len(option_ids), len(labels), len(targets), len(weights))
    rows: list[dict[str, Any]] = []
    for index in range(slot_count):
        raw_id = (option_ids[index] if index < len(option_ids) else "").strip()
        label = labels[index] if index < len(labels) else ""
        target_raw = (targets[index] if index < len(targets) else "").strip()
        weight_raw = (weights[index] if index < len(weights) else "").strip()
        if not raw_id and not target_raw:
            continue
        values, error = _parse_option_values(
            conn,
            page_type,
            {"label": label, "target_page_id": target_raw, "weight": weight_raw},
        )
        if values is None:
            return None, error
        if raw_id:
            try:
                option_id: int | None = int(raw_id)
            except ValueError:
                return None, "invalid option id"
        else:
            option_id = None
        rows.append({"id": option_id, "values": values})
    if page_type == "chance" and rows:
        total = sum(row["values"]["weight"] or 0 for row in rows)
        if total != WEIGHT_TOTAL:
            return None, ERR_WEIGHT_SUM
    return rows, None


def _apply_option_rows(
    conn: sqlite3.Connection, page_id: int, rows: list[dict[str, Any]]
) -> None:
    """Persist parsed option rows, inserting new rows in their form order."""
    submitted_ids = {row["id"] for row in rows if row["id"] is not None}
    existing_ids = {
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM options WHERE page_id = ?", (page_id,)
        ).fetchall()
    }
    # An existing option missing from the submitted rows was removed in the form.
    for option_id in existing_ids - submitted_ids:
        conn.execute(
            "DELETE FROM options WHERE id = ? AND page_id = ?", (option_id, page_id)
        )
    for position, row in enumerate(rows):
        values = row["values"]
        if row["id"] is None:
            conn.execute(
                "INSERT INTO options "
                "(page_id, target_page_id, label, weight, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    page_id,
                    values["target_page_id"],
                    values["label"],
                    values["weight"],
                    position,
                ),
            )
        else:
            conn.execute(
                "UPDATE options SET target_page_id = ?, label = ?, weight = ?, "
                "position = ? WHERE id = ? AND page_id = ?",
                (
                    values["target_page_id"],
                    values["label"],
                    values["weight"],
                    position,
                    row["id"],
                    page_id,
                ),
            )


def create_app() -> Flask:
    """Build and return the Flask application."""
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")
    # A process-wide default RNG keeps chance rolls working under gunicorn;
    # tests inject a seeded random.Random after create_app() to make rolls
    # deterministic (Issue #4).
    app.config.setdefault("RNG", random.Random())
    db.init_app(app)
    database_path = str(app.config["DATABASE_PATH"])
    db.init_db(database_path)
    bootstrap_admin(database_path)

    @app.before_request
    def require_admin_login() -> Any:
        if request.path.startswith("/admin") and not session.get("admin_authenticated"):
            return redirect(url_for("login"))
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login() -> Any:
        if request.method == "POST":
            conn = db.get_db()
            username = db.get_setting(conn, "admin_username")
            password_hash = db.get_setting(conn, "admin_password_hash")
            if (
                username is not None
                and password_hash is not None
                and request.form.get("username") == username
                and check_password_hash(password_hash, request.form.get("password", ""))
            ):
                session["admin_authenticated"] = True
                return redirect(url_for("admin_home"))
            return render_template("login.html"), 401
        return render_template("login.html")

    @app.post("/logout")
    def logout() -> Any:
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    def index() -> Any:
        if db.resolve_start_page_id(db.get_db()) is None:
            return redirect(url_for("login"))
        return render_template("player.html")

    @app.get("/api/start")
    def api_start() -> Any:
        return jsonify({"page_id": db.resolve_start_page_id(db.get_db())})

    @app.get("/api/pages/<int:page_id>")
    def api_page(page_id: int) -> Any:
        conn = db.get_db()
        page = conn.execute(
            "SELECT id, type, title, body_text, image_id FROM pages WHERE id = ?",
            (page_id,),
        ).fetchone()
        if page is None:
            abort(404)
        image_id = page["image_id"]
        payload: dict[str, Any] = {
            "id": page["id"],
            "type": page["type"],
            "title": page["title"],
            "body_text": page["body_text"],
            "image_url": f"/images/{image_id}" if image_id is not None else None,
        }
        if page["type"] != "chance":
            options = conn.execute(
                "SELECT id, label, target_page_id FROM options "
                "WHERE page_id = ? ORDER BY position, id",
                (page_id,),
            ).fetchall()
            payload["options"] = [
                {
                    "id": option["id"],
                    "label": option["label"],
                    "target_page_id": option["target_page_id"],
                }
                for option in options
            ]
        return jsonify(payload)

    @app.post("/api/pages/<int:page_id>/roll")
    def api_roll(page_id: int) -> Any:
        conn = db.get_db()
        page = conn.execute("SELECT type FROM pages WHERE id = ?", (page_id,)).fetchone()
        if page is None:
            abort(404)
        if page["type"] != "chance":
            abort(400)
        options = conn.execute(
            "SELECT target_page_id, weight FROM options "
            "WHERE page_id = ? ORDER BY position, id",
            (page_id,),
        ).fetchall()
        rng = current_app.config["RNG"]
        target = player.roll(
            [(option["target_page_id"], option["weight"]) for option in options], rng
        )
        return jsonify({"page_id": target})

    @app.get("/admin")
    def admin_home() -> Any:
        return redirect(url_for("admin_pages"))

    @app.get("/admin/pages")
    def admin_pages() -> Any:
        conn = db.get_db()
        # The list is for management; the graph above it is how structure is
        # read. A choice's children sit side by side beneath it rather than
        # being strung together inline, and every node links to its editor.
        graph = build_graph(conn)
        pages = conn.execute(
            "SELECT id, type, title, position FROM pages ORDER BY position, id"
        ).fetchall()
        return render_template(
            "admin/pages_list.html",
            pages=pages,
            graph=graph,
            layout=layout_graph(graph),
        )

    @app.route("/admin/pages/new", methods=["GET", "POST"])
    def admin_new_page() -> Any:
        conn = db.get_db()
        if request.method == "POST":
            page_type = request.form.get("type", "")
            if page_type not in ALLOWED_PAGE_TYPES:
                return _render_page_form(None, ERR_INVALID_PAGE_TYPE)
            image_id: int | None = None
            file = request.files.get("image")
            if _is_upload(file):
                assert file is not None
                try:
                    image_id = _insert_image(conn, file)
                except ImageUploadError as exc:
                    return _render_page_form(None, exc.message, status=exc.status)
            cursor = conn.execute(
                "INSERT INTO pages (type, title, body_text, image_id, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    page_type,
                    request.form.get("title", ""),
                    request.form.get("body_text", ""),
                    image_id,
                    conn.execute(
                        "SELECT COALESCE(MAX(position), -1) + 1 FROM pages"
                    ).fetchone()[0],
                ),
            )
            new_page_id = int(cursor.lastrowid or 0)
            # Each parallel label / target_page_id / weight slot in the form
            # is one initial option, so the operator can attach several
            # options in the same POST. Slots without a target are skipped
            # silently; invalid slots are skipped so the page itself still
            # gets created.
            _create_initial_options(conn, new_page_id, page_type, request.form)
            conn.commit()
            return redirect(url_for("admin_pages"))
        pages_rows = conn.execute(
            "SELECT id, title FROM pages ORDER BY position, id"
        ).fetchall()
        return _render_page_form(None, None, pages=pages_rows)

    @app.route("/admin/pages/<int:page_id>/edit", methods=["GET", "POST"])
    def admin_edit_page(page_id: int) -> Any:
        conn = db.get_db()
        page = conn.execute(
            "SELECT id, type, title, body_text, image_id FROM pages WHERE id = ?",
            (page_id,),
        ).fetchone()
        if page is None:
            abort(404)
        if request.method == "POST":
            page_type = request.form.get("type", "")
            if page_type not in ALLOWED_PAGE_TYPES:
                return _render_page_form(page, ERR_INVALID_PAGE_TYPE)
            image_id = page["image_id"]
            file = request.files.get("image")
            if _is_upload(file):
                assert file is not None
                try:
                    # Replacement: a new images row, then repoint pages.image_id.
                    image_id = _insert_image(conn, file)
                except ImageUploadError as exc:
                    return _render_page_form(page, exc.message, status=exc.status)
            option_rows, option_error = _parse_submitted_options(
                conn, page_type, request.form
            )
            if option_rows is None:
                # Reject the whole save: discard the uncommitted placeholder
                # pages and image upload, then re-render the operator's error.
                conn.rollback()
                options_rows = conn.execute(
                    "SELECT id, target_page_id, label, weight, position FROM options "
                    "WHERE page_id = ? ORDER BY position, id",
                    (page_id,),
                ).fetchall()
                pages_rows = conn.execute(
                    "SELECT id, title FROM pages ORDER BY position, id"
                ).fetchall()
                return _render_page_form(
                    page, option_error, options=options_rows, pages=pages_rows
                )
            conn.execute(
                "UPDATE pages SET type = ?, title = ?, body_text = ?, image_id = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (
                    page_type,
                    request.form.get("title", ""),
                    request.form.get("body_text", ""),
                    image_id,
                    page_id,
                ),
            )
            _apply_option_rows(conn, page_id, option_rows)
            conn.commit()
            return redirect(url_for("admin_pages"))
        options_rows = conn.execute(
            "SELECT id, target_page_id, label, weight, position FROM options "
            "WHERE page_id = ? ORDER BY position, id",
            (page_id,),
        ).fetchall()
        pages_rows = conn.execute(
            "SELECT id, title FROM pages ORDER BY position, id"
        ).fetchall()
        return _render_page_form(page, None, options=options_rows, pages=pages_rows)

    @app.post("/admin/pages/<int:page_id>/delete")
    def admin_delete_page(page_id: int) -> Any:
        conn = db.get_db()
        conn.execute("DELETE FROM pages WHERE id = ?", (page_id,))
        conn.commit()
        return redirect(url_for("admin_pages"))

    @app.post("/admin/pages/<int:page_id>/options/new")
    def admin_add_option(page_id: int) -> Any:
        conn = db.get_db()
        page = conn.execute("SELECT type FROM pages WHERE id = ?", (page_id,)).fetchone()
        if page is None:
            abort(404)
        existing_sum = conn.execute(
            "SELECT COALESCE(SUM(weight), 0) FROM options WHERE page_id = ?",
            (page_id,),
        ).fetchone()[0]
        values, error = _parse_option(
            conn, page["type"], request.form, existing_sum=existing_sum
        )
        if values is None:
            return error or "invalid option"
        position = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM options WHERE page_id = ?",
            (page_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO options (page_id, target_page_id, label, weight, position) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                page_id,
                values["target_page_id"],
                values["label"],
                values["weight"],
                position,
            ),
        )
        conn.commit()
        return redirect(url_for("admin_edit_page", page_id=page_id))

    @app.post("/admin/pages/<int:page_id>/options/<int:option_id>/edit")
    def admin_edit_option(page_id: int, option_id: int) -> Any:
        conn = db.get_db()
        page = conn.execute("SELECT type FROM pages WHERE id = ?", (page_id,)).fetchone()
        if page is None:
            abort(404)
        option = conn.execute(
            "SELECT id FROM options WHERE id = ? AND page_id = ?",
            (option_id, page_id),
        ).fetchone()
        if option is None:
            abort(404)
        existing_sum = conn.execute(
            "SELECT COALESCE(SUM(weight), 0) FROM options WHERE page_id = ? AND id != ?",
            (page_id, option_id),
        ).fetchone()[0]
        values, error = _parse_option(
            conn, page["type"], request.form, existing_sum=existing_sum
        )
        if values is None:
            return error or "invalid option"
        conn.execute(
            "UPDATE options SET target_page_id = ?, label = ?, weight = ? WHERE id = ?",
            (
                values["target_page_id"],
                values["label"],
                values["weight"],
                option_id,
            ),
        )
        conn.commit()
        return redirect(url_for("admin_edit_page", page_id=page_id))

    @app.post("/admin/pages/<int:page_id>/options/<int:option_id>/delete")
    def admin_delete_option(page_id: int, option_id: int) -> Any:
        conn = db.get_db()
        conn.execute(
            "DELETE FROM options WHERE id = ? AND page_id = ?", (option_id, page_id)
        )
        conn.commit()
        return redirect(url_for("admin_edit_page", page_id=page_id))

    @app.post("/admin/pages/<int:page_id>/options/reorder")
    def admin_reorder_options(page_id: int) -> Any:
        conn = db.get_db()
        for position, raw_option_id in enumerate(request.form.getlist("option_id")):
            try:
                option_id = int(raw_option_id)
            except ValueError:
                continue
            conn.execute(
                "UPDATE options SET position = ? WHERE id = ? AND page_id = ?",
                (position, option_id, page_id),
            )
        conn.commit()
        return redirect(url_for("admin_edit_page", page_id=page_id))

    @app.get("/admin/map")
    def admin_map() -> Any:
        conn = db.get_db()
        graph = build_graph(conn)
        return render_template("admin/map.html", graph=graph, layout=layout_graph(graph))

    @app.route("/admin/settings", methods=["GET", "POST"])
    def admin_settings() -> Any:
        conn = db.get_db()
        error: str | None = None
        if request.method == "POST":
            raw_start = (request.form.get("start_page_id") or "").strip()
            if raw_start:
                try:
                    start_page_id = int(raw_start)
                except ValueError:
                    error = "start_page_id must be an integer"
                else:
                    exists = conn.execute(
                        "SELECT id FROM pages WHERE id = ?", (start_page_id,)
                    ).fetchone()
                    if exists is None:
                        error = "start_page_id must reference an existing page"
                    else:
                        conn.execute(
                            "INSERT INTO settings (key, value) "
                            "VALUES ('start_page_id', ?) "
                            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                            (str(start_page_id),),
                        )
            password = request.form.get("password", "")
            if error is None and password:
                conn.execute(
                    "INSERT INTO settings (key, value) "
                    "VALUES ('admin_password_hash', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (generate_password_hash(password),),
                )
            if error is None:
                conn.commit()
                return redirect(url_for("admin_settings"))
        pages = conn.execute(
            "SELECT id, title FROM pages ORDER BY position, id"
        ).fetchall()
        return render_template(
            "admin/settings.html",
            pages=pages,
            selected=db.get_start_page_id(conn),
            error=error,
        )

    @app.post("/admin/images")
    def admin_upload_image() -> Any:
        conn = db.get_db()
        file = request.files.get("file")
        if file is None or file.filename is None or file.filename == "":
            abort(400)
        try:
            image_id = _insert_image(conn, file)
        except ImageUploadError as exc:
            abort(exc.status)
        conn.commit()
        return jsonify({"id": image_id}), 201

    @app.get("/images/<int:image_id>")
    def serve_image(image_id: int) -> Any:
        conn = db.get_db()
        row = conn.execute(
            "SELECT content_type, data FROM images WHERE id = ?", (image_id,)
        ).fetchone()
        if row is None:
            abort(404)
        return (
            row["data"],
            200,
            {
                "Content-Type": row["content_type"],
                "Cache-Control": "public, max-age=86400, immutable",
            },
        )

    return app

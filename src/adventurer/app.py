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


def _render_page_form(
    page: Any, error: str | None, *, status: int = 200
) -> tuple[str, int]:
    """Render the page create/edit form with the shared type/format constants."""
    return (
        render_template(
            "admin/page_form.html",
            page=page,
            error=error,
            page_types=PAGE_TYPES,
            image_types=IMAGE_TYPES,
        ),
        status,
    )


def _parse_option(
    page_type: str, form: Any, *, existing_sum: int = 0
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate an option form for ``page_type``; return ``(values, error)``."""
    if page_type == "ending":
        return None, ERR_ENDING_OPTIONS
    label = form.get("label", "")
    target_raw = (form.get("target_page_id") or "").strip()
    weight_raw = (form.get("weight") or "").strip()
    if not target_raw:
        return None, ERR_TARGET_REQUIRED
    try:
        target_page_id = int(target_raw)
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
    if existing_sum + weight != WEIGHT_TOTAL:
        return None, ERR_WEIGHT_SUM
    return {
        "label": label,
        "target_page_id": target_page_id,
        "weight": weight,
    }, None


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
        pages = conn.execute(
            "SELECT id, type, title, position FROM pages ORDER BY position, id"
        ).fetchall()
        targets_by_page: dict[int, list[str]] = {}
        for row in conn.execute(
            "SELECT o.page_id, p.title FROM options o "
            "JOIN pages p ON o.target_page_id = p.id "
            "ORDER BY o.position, o.id"
        ).fetchall():
            targets_by_page.setdefault(row["page_id"], []).append(str(row["title"]))
        pages_with_targets = [
            {**dict(page), "targets": targets_by_page.get(page["id"], [])}
            for page in pages
        ]
        return render_template("admin/pages_list.html", pages=pages_with_targets)

    @app.route("/admin/pages/new", methods=["GET", "POST"])
    def admin_new_page() -> Any:
        if request.method == "POST":
            page_type = request.form.get("type", "")
            if page_type not in ALLOWED_PAGE_TYPES:
                return _render_page_form(None, ERR_INVALID_PAGE_TYPE)
            conn = db.get_db()
            image_id: int | None = None
            file = request.files.get("image")
            if _is_upload(file):
                assert file is not None
                try:
                    image_id = _insert_image(conn, file)
                except ImageUploadError as exc:
                    return _render_page_form(None, exc.message, status=exc.status)
            conn.execute(
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
            conn.commit()
            return redirect(url_for("admin_pages"))
        return _render_page_form(None, None)

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
            conn.commit()
            return redirect(url_for("admin_pages"))
        return _render_page_form(page, None)

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
            page["type"], request.form, existing_sum=existing_sum
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
            page["type"], request.form, existing_sum=existing_sum
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

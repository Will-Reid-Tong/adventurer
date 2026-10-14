"""Images seam: the admin upload route and ``GET /images/<id>``.

Pins the Issue #5 contract:

- a multipart upload stores the file and returns the new image id;
- serving that id round-trips the exact bytes with the stored content type and
  the ``Cache-Control: public, max-age=86400, immutable`` header;
- uploads larger than 5 MB are rejected;
- content types outside jpg / png / webp / gif are rejected;
- an unknown image id returns 404.

The upload route is guarded by admin authentication (#6), so this test logs in
before exercising it.
"""

import base64
import io
from pathlib import Path

from werkzeug.security import generate_password_hash

from cyoa import create_app, db

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "correct horse battery staple"

# A real 1x1 transparent PNG so magic-byte validation (where the implementation
# does it) accepts the upload.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def test_images_upload_and_serve_seam(tmp_path: Path, monkeypatch) -> None:
    db_path = str(tmp_path / "app.db")
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
    monkeypatch.setenv("DATABASE_PATH", db_path)
    client = create_app().test_client()
    client.post("/login", data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD})

    # Upload -> 201 carrying the new image id.
    upload = client.post(
        "/admin/images",
        data={"file": (io.BytesIO(PNG_BYTES), "cover.png", "image/png")},
        content_type="multipart/form-data",
    )
    assert upload.status_code == 201
    image_id = upload.get_json()["id"]

    # Serve -> exact bytes, stored content type, immutable cache header.
    served = client.get(f"/images/{image_id}")
    assert served.status_code == 200
    assert served.data == PNG_BYTES
    assert served.headers["Content-Type"] == "image/png"
    assert served.headers["Cache-Control"] == "public, max-age=86400, immutable"

    # Oversize upload (> 5 MB) is rejected.
    oversize = client.post(
        "/admin/images",
        data={
            "file": (
                io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * MAX_UPLOAD_BYTES),
                "huge.png",
                "image/png",
            )
        },
        content_type="multipart/form-data",
    )
    assert oversize.status_code == 413

    # A format outside jpg / png / webp / gif is rejected.
    disallowed = client.post(
        "/admin/images",
        data={"file": (io.BytesIO(b"not an image"), "notes.txt", "text/plain")},
        content_type="multipart/form-data",
    )
    assert disallowed.status_code == 400

    # Unknown image id -> 404.
    assert client.get("/images/9999").status_code == 404

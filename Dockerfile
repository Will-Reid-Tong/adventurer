# syntax=docker/dockerfile:1

# --- Build stage -----------------------------------------------------------
# Resolve the locked dependency set into /app/.venv with uv. The tag pins the
# uv version that wrote uv.lock (0.13.1) on Python 3.14 / Debian trixie-slim,
# matching the runtime stage below so the copied venv stays portable.
FROM ghcr.io/astral-sh/uv:0.13.1-python3.14-trixie-slim AS builder

# Copy packages into the venv instead of hardlinking from the uv cache: the
# cache lives on another filesystem and the venv is copied into the next stage.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# README.md is referenced by pyproject.toml and required by the build backend.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev

# --- Runtime stage ---------------------------------------------------------
FROM python:3.14-slim

# Run as an unprivileged user that owns the app and the data volume.
RUN groupadd --gid 1001 app \
    && useradd --uid 1001 --gid 1001 --no-create-home \
        --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

# Copy the pre-built environment and application source from the builder.
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" \
    DATABASE_PATH=/data/app.db \
    PYTHONUNBUFFERED=1

# The SQLite database (including image BLOBs) is the entire persistent state.
RUN mkdir -p /data && chown app:app /data
VOLUME /data

COPY --chown=app:app docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 755 /usr/local/bin/docker-entrypoint.sh

USER app

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "adventurer:create_app()"]

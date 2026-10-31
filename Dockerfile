# syntax=docker/dockerfile:1
# Two stages. The build stage compiles the Reflex frontend once; the runtime
# stage carries the result and no Bun, so a container starts in seconds
# instead of rebuilding the frontend on every start.
# uv as a stage of its own: Dependabot's docker updates read FROM lines.
FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv
FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913 AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /bin/uv
# The venv lives where the app looks for it: pages start scripts with
# hearth/.venv/bin/python (core/state.py:721, pages/music.py, pages/dates.py:841).
ENV VIRTUAL_ENV=/app/hearth/.venv PATH=/app/hearth/.venv/bin:$PATH
RUN uv venv $VIRTUAL_ENV
COPY hearth/requirements.txt /app/hearth/requirements.txt
RUN uv pip install -r /app/hearth/requirements.txt
COPY . /app
RUN uv pip install --no-deps -e /app/hearth
WORKDIR /app/hearth
# Ports pinned for the export: unset, `reflex export` bakes the default backend
# URL (http://localhost:8000, reflex_base/config.py:210) into the frontend, and
# the websocket would dial a port nothing listens on.
RUN REFLEX_FRONTEND_PORT=3000 REFLEX_BACKEND_PORT=3000 \
    reflex export --frontend-only --no-zip --env prod \
 && rm -rf .web/node_modules

FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913
ARG HEARTH_VERSION=dev
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home app
COPY --from=build --chown=app:app /app /app
ENV VIRTUAL_ENV=/app/hearth/.venv PATH=/app/hearth/.venv/bin:$PATH REFLEX_ENV_MODE=prod \
    HEARTH_DATA_DIR=/data HEARTH_BACKUP_DIR=/backups HEARTH_BACKUP_SCHEDULE=1 \
    HEARTH_VERSION=$HEARTH_VERSION TZ=UTC
RUN mkdir -p /data /backups && chown app:app /data /backups
WORKDIR /app/hearth
# Runtime writes (docker diff, 2026-10-05, after GET / and /ping only): .pyc files
# under /app (__pycache__; PYTHONDONTWRITEBYTECODE=1 would stop them) and
# /app/hearth/.web/backend/upload_is_used. Not exercised: hearth.db and
# .states appear only once pages use state and the database.
USER app
VOLUME ["/data", "/backups"]
EXPOSE 3000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["serve"]

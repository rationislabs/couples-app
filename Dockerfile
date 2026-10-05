# syntax=docker/dockerfile:1
# Two stages. The build stage compiles the Reflex frontend once; the runtime
# stage carries the result and no Bun, so a container starts in seconds
# instead of rebuilding the frontend on every start.
FROM python:3.12-slim AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /bin/uv
# The venv lives where the app looks for it: pages start scripts with
# ledger_app/.venv/bin/python (core/state.py:721, pages/music.py, pages/dates.py:841).
ENV VIRTUAL_ENV=/app/ledger_app/.venv PATH=/app/ledger_app/.venv/bin:$PATH
RUN uv venv $VIRTUAL_ENV
COPY ledger_app/requirements.txt /app/ledger_app/requirements.txt
RUN uv pip install -r /app/ledger_app/requirements.txt
COPY . /app
RUN uv pip install --no-deps -e /app/ledger_app
WORKDIR /app/ledger_app
# Ports pinned for the export: unset, `reflex export` bakes the default backend
# URL (http://localhost:8000, reflex_base/config.py:210) into the frontend, and
# the websocket would dial a port nothing listens on.
RUN REFLEX_FRONTEND_PORT=3000 REFLEX_BACKEND_PORT=3000 \
    reflex export --frontend-only --no-zip --env prod \
 && rm -rf .web/node_modules

FROM python:3.12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --uid 10001 --create-home app
COPY --from=build --chown=app:app /app /app
ENV VIRTUAL_ENV=/app/ledger_app/.venv PATH=/app/ledger_app/.venv/bin:$PATH REFLEX_ENV_MODE=prod
WORKDIR /app/ledger_app
# Runtime writes (docker diff, 2026-10-05, after GET / and /ping only): .pyc files
# under /app (__pycache__; PYTHONDONTWRITEBYTECODE=1 would stop them) and
# /app/ledger_app/.web/backend/upload_is_used. Not exercised: ledger.db and
# .states appear only once pages use state and the database.
USER app
EXPOSE 3000
CMD ["python", "-m", "ledger_app.serve"]

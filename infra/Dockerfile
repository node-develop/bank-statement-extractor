# bank-statement-analizer — multi-stage backend Dockerfile.
#
# NOTE: pyproject.toml requires Python >=3.14, which is alpha as of 2026-05.
# Pin to python:3.13-slim until python:3.14-slim ships an official image.
# Bump base tags in one PR; search for "3.13-slim" in this file.
#
# Build context must be the repository root:
#   docker build -f infra/Dockerfile -t bsa-api .

# ---------------------------------------------------------------------------
# Stage 1: uv-base — install uv into the builder image via official image copy.
# Using COPY --from=ghcr.io/astral-sh/uv avoids pip overhead and pins uv
# separately from Python. Pin to a specific digest in prod (see TODO below).
# TODO: pin uv to digest in production, e.g. ghcr.io/astral-sh/uv:0.5.x@sha256:...
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

# Pull the uv binary from the official image (no pip install required).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# uv tuning for Docker:
#   UV_LINK_MODE=copy   — copy files instead of hardlinks (cross-filesystem safe)
#   UV_COMPILE_BYTECODE — pre-compile .pyc so runtime startup is faster
#   UV_PYTHON_DOWNLOADS=0 — use the system Python; don't let uv fetch its own
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# ------------------------------------------------------------------
# Phase 1: install dependencies only (cache-layer discipline, rule 4).
# pyproject.toml + uv.lock are bound at build time via mount; the
# resulting .venv IS materialised into the image via UV_LINK_MODE=copy.
# --mount=type=bind keeps pyproject.toml/uv.lock out of the image layer
# while still making them visible to uv.
# --no-install-project skips installing the src/ package itself so this
# layer is invalidated only when deps change, not on every source edit.
# --extra postgres pulls langgraph-checkpoint-postgres + psycopg[binary].
# --no-dev excludes ruff, mypy, pytest from the runtime image.
# --frozen = fail the build if uv.lock is out of date (rule 4).
# ------------------------------------------------------------------
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --extra postgres --no-dev --no-install-project

# ------------------------------------------------------------------
# Phase 2: copy source and install the project package itself.
# hatchling requires README.md to be present (build-backend reads it).
# We do NOT bind-mount src/ — changes to source code invalidate only
# this layer, not the dependency layer above.
# ------------------------------------------------------------------
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra postgres --no-dev

# ---------------------------------------------------------------------------
# Stage 2: runtime — minimal image, no build tools, no uv binary.
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# libpq5   — shared library required by psycopg[binary] at runtime.
# tini     — minimal init (PID 1 reaper) so SIGTERM propagates correctly.
# No curl/wget — healthcheck uses python -c (saves a layer).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 tini \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user (uid 10001 is arbitrary but non-system).
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app

# Place the virtualenv on PATH before system Python.
# LANGSMITH_TRACING defaults off — enable per-deployment via Dokploy env.
# LANGGRAPH_STRICT_MSGPACK stays true (checkpointer.py enforces this, but
# we set it here as belt-and-suspenders for safety).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANGSMITH_TRACING=false \
    LANGGRAPH_STRICT_MSGPACK=true

WORKDIR /app

# Copy virtualenv and source from builder; chown to non-root user.
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src ./src

# Tini as PID 1 so uvicorn receives SIGTERM cleanly on container stop.
ENTRYPOINT ["/usr/bin/tini", "--"]

USER app
EXPOSE 8000

# Healthcheck: liveness via /healthz (always 200 when process is alive).
# Readiness (/readyz) is checked by Dokploy; liveness check here keeps
# Docker's own view consistent. Uses python urllib — no curl dependency.
# --start-period=20s gives the lifespan (checkpointer + graph compile) time.
HEALTHCHECK --interval=10s --timeout=3s --retries=5 --start-period=20s \
    CMD python -c \
        "import urllib.request, sys; \
         sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"

# --proxy-headers: trust X-Forwarded-* from Traefik/nginx reverse proxy.
CMD ["uvicorn", "src.api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--proxy-headers"]

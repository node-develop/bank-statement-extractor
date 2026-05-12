---
name: dokploy-0_29-deploy
description: Dockerfile, docker-compose, and dokploy.json patterns for deploying the FastAPI service and the React frontend to Dokploy 0.29. Use when packaging the service for deployment or fixing build/healthcheck issues. Do NOT use for local-dev compose (that's `docker-compose.dev.yml`).
---

# Dokploy 0.29 deploy

## Build type

Use `dockerfile` build type — Dokploy 0.29 reads `infra/Dockerfile` and
honors `.dockerignore`. Avoid the Nixpacks path for Python projects with
`uv` — Nixpacks doesn't yet handle uv reliably as of 2026-05.

## Multi-stage Dockerfile (Python)

```dockerfile
# NOTE: Bumping to python:3.14-slim once it ships; until then 3.13-slim.
FROM python:3.13-slim AS builder
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
RUN pip install --no-cache-dir uv==0.4.*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.13-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
RUN useradd -m -u 10001 app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src
USER app
EXPOSE 8000
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## dokploy.json (application manifest)

```json
{
  "applicationType": "dockerfile",
  "dockerfilePath": "infra/Dockerfile",
  "buildContext": ".",
  "port": 8000,
  "healthCheck": {"path": "/readyz", "interval": 30, "timeout": 5, "retries": 3},
  "livenessProbe": {"path": "/healthz"},
  "env": {
    "ANTHROPIC_API_KEY": "${secret:ANTHROPIC_API_KEY}",
    "LANGSMITH_API_KEY": "${secret:LANGSMITH_API_KEY}",
    "LANGSMITH_PROJECT": "bank-statement-analizer-prod",
    "DATABASE_URL": "${service:postgres.url}",
    "FRONTEND_ORIGIN": "https://bsa.example.com"
  }
}
```

## docker-compose.yml (Dokploy renders this on the host)

Services: `api`, `postgres`. Frontend is a separate Dokploy static-site
application built from `frontend/dist`.

## Rules

1. Never bake secrets into the image. All secrets via Dokploy env mapping.
2. Use a non-root user (`app`, uid 10001).
3. Pin uv (`uv==0.4.*`) so the build is reproducible.
4. `--frozen` on `uv sync` — fail the build if `uv.lock` is out of date.
5. Healthcheck endpoint is `/readyz`, not `/`. Hits the ready signal that
   the graph compiled and the Anthropic key is present.

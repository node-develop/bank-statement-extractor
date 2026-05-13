# Deployment runbook — bank-statement-analizer

Two deployable units: the **FastAPI backend** (`bsa-api`) and the **React
frontend** (`bsa-frontend`). Both are Docker images built from the repository
root. Postgres 16 runs as a separate service (LangGraph checkpoint store).

---

## Required environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key (Claude Sonnet / Haiku). Without it `/readyz` returns 503. |
| `DATABASE_URL` | Yes (prod) | `postgresql://user:pass@host:5432/db`. Defaults to SQLite in local dev. |
| `FRONTEND_ORIGIN` | Yes (prod) | Scheme + host the frontend is served from (CORS). Example: `https://bsa.example.com`. |
| `LANGSMITH_API_KEY` | No | LangSmith tracing. Leave unset to disable. |
| `LANGSMITH_PROJECT` | No | Defaults to `bank-statement-analizer-dev`. |
| `LANGSMITH_TRACING` | No | `"true"` to enable. Defaults to `"false"`. |

Never commit these values. Supply via shell environment, a `.env` file (git-ignored), or Dokploy's secret store.

---

## Local build and smoke-test

```bash
# From the repository root:
export ANTHROPIC_API_KEY=sk-ant-...    # required

# Build and start all three services
docker compose -f infra/docker-compose.yml up --build

# Liveness (always 200 when the process is alive)
curl -fsS http://localhost:8000/healthz
# → {"status":"ok"}

# Readiness (503 without a valid ANTHROPIC_API_KEY or before lifespan completes)
curl -fsS http://localhost:8000/readyz
# → {"status":"ready"} once lifespan finishes (≤ 20 s)

# Frontend SPA
curl -fsS http://localhost/
# → HTML

# API via nginx proxy (the /api/ prefix is stripped by nginx)
curl -fsS http://localhost/api/healthz
# → {"status":"ok"}
```

### Build the images individually

```bash
docker build -f infra/Dockerfile -t bsa-api:dev .
docker image inspect bsa-api:dev --format '{{.Size}}'
# Expect < 500_000_000 bytes (~350 MB with all Python deps)

docker build -f infra/Dockerfile.frontend -t bsa-frontend:dev .
docker image inspect bsa-frontend:dev --format '{{.Size}}'
# Expect < 50_000_000 bytes (~30 MB nginx + static dist)
```

---

## Healthcheck semantics

| Endpoint | Probe type | Returns 200 when |
|---|---|---|
| `/healthz` | Liveness | The Python process is alive (always). |
| `/readyz` | Readiness | `ANTHROPIC_API_KEY` is set **and** the lifespan has completed (checkpointer connected, graph compiled). |

Dokploy uses `/readyz` as the readiness gate before routing traffic. Allow
20–30 seconds for the lifespan to complete on first start (graph compilation
imports several large packages).

---

## Dokploy 0.29 deployment

### Step 1 — import the manifest

In the Dokploy UI: Projects → New Project → Import from file → select
`infra/dokploy.json`. This creates two application entries and one database
entry.

### Step 2 — set project-level environment variables

In the Dokploy project settings add these secrets before the first deploy:

| Key | Example value |
|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` |
| `BSA_API_DOMAIN` | `api.bsa.example.com` |
| `BSA_FRONTEND_DOMAIN` | `bsa.example.com` |
| `BSA_POSTGRES_PASSWORD` | (generate: `openssl rand -hex 24`) |
| `DATABASE_URL` | Constructed by Dokploy from the `databases[]` entry; copy from the DB service details page. |
| `FRONTEND_ORIGIN` | `https://bsa.example.com` (must match `BSA_FRONTEND_DOMAIN`) |
| `LANGSMITH_API_KEY` | Optional — leave blank to disable tracing. |
| `LANGSMITH_PROJECT` | `bank-statement-analizer-prod` |

### Step 3 — deploy

Deploy the `postgres` database first (Dokploy UI → Deploy), wait for it to
show "healthy", then deploy the API, then the frontend.

The API's `/readyz` endpoint will return 503 until `ANTHROPIC_API_KEY` is set
and the lifespan has finished. Dokploy will retry automatically.

### Dokploy manifest field notes

`infra/dokploy.json` contains inline `_notes` entries flagging two fields
whose exact names differ between the 0.29 schema reference and the SKILL.md
examples (`buildType` vs `applicationType`, `livenessPath` vs `livenessProbe`).
If the manifest import fails validation, apply the rename described in those
notes and re-import.

---

## Postgres connection issues

- `DATABASE_URL` must use the `postgresql://` scheme (not `postgres://` — psycopg3
  requires the canonical form).
- If the API crashes on startup with `could not connect to server`, confirm the
  postgres container is healthy: `docker compose -f infra/docker-compose.yml ps`.
- `LANGGRAPH_CHECKPOINTER` defaults to `sqlite` in the Dockerfile env; the compose
  file overrides it to `postgres`. If you run the API image outside compose without
  setting this variable, it will use SQLite (file at `./graph.sqlite`).

## CORS errors

`FRONTEND_ORIGIN` must be an exact scheme + host match (no trailing slash) for the
browser's `Origin` header. If the frontend is served over HTTPS on a custom domain,
set `FRONTEND_ORIGIN=https://bsa.example.com` accordingly. Mismatches produce
`CORS` errors in the browser console — check the `Origin` header in the preflight
request and compare it to the running value with:

```bash
docker compose -f infra/docker-compose.yml exec api env | grep FRONTEND_ORIGIN
```

## Image size

If the backend image exceeds 500 MB:
1. Confirm `.venv` in the builder is only deps + postgres extra (no dev extras).
2. Check `infra/.dockerignore` is excluding `Task/` (large PDF) and `tests/`.
3. Run `docker image history bsa-api:dev` to identify large layers.

## Python 3.14 upgrade path

When `python:3.14-slim` ships an official image (expected late 2026):
1. Update the `FROM python:3.13-slim` lines in `infra/Dockerfile` (two occurrences).
2. Update `[tool.ruff] target-version` and `[tool.mypy] python_version` in `pyproject.toml`.
3. Verify `uv run mypy src` is clean.
4. Open a single PR with those changes and no other code changes.

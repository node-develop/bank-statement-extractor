# bank-statement-analizer

HTTP service that turns a bank-statement PDF into structured
`{account, summary, transactions}` JSON, one block per statement period.
Extraction is driven by a LangGraph pipeline backed by Anthropic Claude
(Haiku 4.5 for routing and classification, Sonnet 4.6 for transactions);
a pure-Python reconciliation step verifies the balance algebra
`beginning + Σdeposits − Σwithdrawals = ending ± $0.01` for every period.
A Vite + React + TypeScript SPA drives the upload flow.

![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![python: 3.14](https://img.shields.io/badge/python-3.14-blue.svg)
![react: 19](https://img.shields.io/badge/react-19-61dafb.svg)
![langgraph: 1.x](https://img.shields.io/badge/langgraph-1.x-orange.svg)

## Highlights

- Multi-period statements — one PDF can carry many cycles; each period is
  extracted and reconciled independently.
- Fail-loud reconciliation — when the balance equation drifts beyond
  `Decimal("0.01")` the response carries `reconciled: false`, a signed
  `delta` and a `notes[]` list. Numbers are never silently averaged.
- Deterministic verifier (six structural checks) plus a Haiku-4.5 critic
  loop that re-extracts suspect periods with targeted hints.
- Human-in-the-loop pause via LangGraph `interrupt()` when too many
  suspects survive or the LLM cost cap is hit; the run is resumed from a
  review modal in the frontend.
- Server-side OCR fallback for image-based PDFs — prefers Azure Document
  Intelligence when configured, otherwise uses bundled
  Tesseract / `ocrmypdf`.
- SSE progress stream on `POST /extract/stream` for live per-node updates.
- Optional LangSmith tracing for every run.
- Decimal precision end-to-end: monetary values stay as `Decimal` in
  Python and are serialised as quoted JSON strings on the wire.

## Table of contents

- [Quick start](#quick-start)
- [HTTP API](#http-api)
- [Configuration](#configuration)
- [Architecture](#architecture)
- [Reconciliation contract](#reconciliation-contract)
- [Sample data](#sample-data)
- [Development](#development)
- [Repository layout](#repository-layout)
- [License](#license)

## Quick start

The fastest path is Docker Compose. Local dev needs Python 3.14 and
`uv 0.5+`; the frontend needs Node 22 and `pnpm 10+`.

### Docker Compose

```bash
git clone https://github.com/node-develop/bank-statement-extractor.git
cd bank-statement-extractor
cp .env.example .env                                # then edit .env
docker compose --env-file .env -f infra/docker-compose.yml up --build
```

The compose stack publishes:

| Service  | Port | URL                       |
|----------|-----:|---------------------------|
| api      | 8000 | http://localhost:8000     |
| frontend |   80 | http://localhost          |

A named volume (`bsa_data`) persists the LangGraph SQLite checkpoint
between restarts.

### Local development

```bash
git clone https://github.com/node-develop/bank-statement-extractor.git
cd bank-statement-extractor
cp .env.example .env                                # then edit .env

# Backend
uv sync --extra dev
uv run uvicorn src.api.main:app --reload            # http://localhost:8000

# Frontend (in another terminal)
cd frontend
pnpm install
pnpm dev                                            # http://localhost:5173
```

Set `FRONTEND_ORIGIN=http://localhost:5173` in `.env` so CORS lets the
Vite dev server talk to the API.

### Eval on the bundled Ixonia sample

```bash
uv run python -m src.evals.run \
    --statement Task/Binder2_Redacted.pdf \
    --txt Task/ixonia_binder2_ocr.txt
```

The runner asserts exact-match on every summary field and transaction
count across the 10 statement periods that ship in `Task/`.

## HTTP API

| Method | Path                              | Purpose                                                       |
|--------|-----------------------------------|---------------------------------------------------------------|
| GET    | `/healthz`                        | Liveness probe; `200 {"status":"ok"}` while the process is up.|
| GET    | `/readyz`                         | Readiness probe; `503` until `ANTHROPIC_API_KEY` is set and the graph is compiled. |
| POST   | `/extract`                        | Multipart upload; returns the assembled `ExtractResult`.      |
| POST   | `/extract/stream`                 | Same contract; returns an SSE stream of per-node events.      |
| GET    | `/pending_review`                 | List the most-recent paused extractions awaiting review.      |
| GET    | `/review/{extraction_id}`         | Fetch one paused extraction's suspects + chunk excerpts.      |
| POST   | `/review/{extraction_id}`         | Submit human corrections and resume the paused graph.         |

### Upload constraints

- `file` — required, `application/pdf`, **≤ 80 MB**.
- `ocr_text` — optional, `text/plain`, **≤ 5 MB**. When supplied, the
  ingest node skips the OCR fallback entirely and uses the provided text.

Returns:

- `200` — extraction complete; body is the JSON `ExtractResult`.
- `413` — PDF over 80 MB.
- `415` — content type is not a PDF MIME type.
- `422` — PDF unreadable (corrupt, encrypted, zero pages).
- `5xx` — unhandled error.

Monetary fields are quoted JSON strings (e.g. `"597068.70"`). Parse them
with `decimal.Decimal` in Python or `decimal.js` in JavaScript to avoid
binary-float drift.

### Example

```bash
curl -F "file=@Task/Binder2_Redacted.pdf;type=application/pdf" \
     -F "ocr_text=@Task/ixonia_binder2_ocr.txt;type=text/plain" \
     http://localhost:8000/extract | jq '.periods[0].summary'
```

## Configuration

Configuration is environment-driven. Copy `.env.example` to `.env` and
fill in the values you need. Only `ANTHROPIC_API_KEY` is strictly required;
every other variable has a documented default.

| Variable                     | Required | Default                              | Notes                                                                    |
|------------------------------|:--------:|--------------------------------------|--------------------------------------------------------------------------|
| `ANTHROPIC_API_KEY`          |   yes    | —                                    | Claude API key; billed for both Haiku and Sonnet calls.                  |
| `LANGSMITH_API_KEY`          |    no    | —                                    | Enables tracing of every graph run.                                      |
| `LANGSMITH_PROJECT`          |    no    | `bank-statement`                     | Compose overrides to `bank-statement-analizer-dev`.                      |
| `LANGSMITH_TRACING`          |    no    | `false`                              | Set to `true` once a LangSmith key is present.                           |
| `LANGSMITH_ENDPOINT`         |    no    | `https://api.smith.langchain.com`    | Override for self-hosted LangSmith.                                      |
| `FRONTEND_ORIGIN`            |    no    | `http://localhost:5173`              | CORS origin. Compose sets it to `http://localhost`.                      |
| `AZURE_DI_ENDPOINT`          |    no    | —                                    | Azure Document Intelligence endpoint. Both AZURE_DI_* must be set.       |
| `AZURE_DI_KEY`               |    no    | —                                    | Azure DI key; preferred over Tesseract when present.                     |
| `LANGGRAPH_CHECKPOINTER`     |    no    | `sqlite`                             | `sqlite` (default) or `memory` (tests).                                  |
| `LANGGRAPH_SQLITE_PATH`      |    no    | `./graph.sqlite`                     | Compose mounts `/app/data/graph.sqlite` on a named volume.               |
| `BSA_COST_CAP_USD`           |    no    | `5.00`                               | Cumulative LLM cost ceiling; over this the graph routes to HITL.         |
| `BSA_AWAIT_REVIEW_SUSPECTS`  |    no    | `3` (code), `25` (compose)           | Suspect count above which the graph pauses for human review.             |
| `LOG_LEVEL`                  |    no    | `INFO`                               | Standard Python log levels.                                              |
| `REVIEWS_DB_PATH`            |    no    | `./reviews.sqlite`                   | Pending-reviews store; mounted at `/app/data/reviews.sqlite` in compose. |
| `LANGGRAPH_STRICT_MSGPACK`   |    no    | `true`                               | Restricts checkpoint deserialisation. Keep `true` in production.         |

See `.env.example` for the full file with inline comments.

## Architecture

A single PDF may contain multiple statement periods. The graph splits
the raw text into one `PeriodChunk` per period and fans the four
extractors out in parallel via LangGraph's `Send` API. A deterministic
verifier inspects the merged state, and a router decides whether to
reconcile, retry through the critic loop, or pause for human review.

```
                              START
                                │
                                ▼
                             ingest            (pdfplumber → pypdf
                                │               → Azure DI / Tesseract
                                ▼               fallback)
                          split_periods        (deterministic regex)
                                │
                ┌───────────────┼─────── Send (one per chunk × 4) ───────┐
                ▼               ▼              ▼                         ▼
        classify_layout   extract_account  extract_summary   extract_transactions
                └───────────────┴──────────────┴──────────┬──────────────┘
                                                          ▼
                                                    merge_state
                                                          │
                                                          ▼
                                                      verifier           (C1-C6 checks)
                                                          │
                                          ┌───────────────┼───────────────┐
                                          ▼               ▼               ▼
                                      reconcile        critic        await_review
                                          │               │               │
                                          │               ▼               ▼
                                          │       apply_critic_hint   (interrupt;
                                          │               │            resume via
                                          │               ▼            POST /review)
                                          │          [Send loop]           │
                                          │                                │
                                          ▼                                ▼
                                      finalize ◄──────────────────────── finalize
                                          │
                                          ▼
                                         END
```

- Per-period results merge back into list-shaped state via
  `operator.add` reducers, so parallel branches compose safely.
- LangGraph's SQLite checkpointer persists state between steps so the
  HITL `interrupt()` can resume cleanly.
- A cumulative-cost reducer (`Decimal`) enforces a hard per-request
  ceiling (`BSA_COST_CAP_USD`); when crossed, the router skips the
  critic and routes to `await_review`.

## Reconciliation contract

For every statement period the service computes:

```
beginning_balance + Σdeposits − Σwithdrawals = ending_balance  ± $0.01
```

When the invariant fails the response carries:

```jsonc
{
  "reconciled": false,
  "delta": "-12.34",
  "notes": [
    "deposits_total mismatch: extracted 1214254.05, summed 1214266.39",
    "withdrawals_count mismatch: extracted 111, counted 110"
  ]
}
```

Numbers are never silently corrected. If the deterministic verifier
finds 1–3 suspect periods after the first pass and the cost cap has not
been hit, the critic loop (up to two retries) re-extracts problematic
chunks with targeted hints. Beyond that threshold — or when cumulative
LLM cost crosses `BSA_COST_CAP_USD` — the graph pauses, and the API
returns a partial `ExtractResult` plus a `pending_review` record. The
frontend's review modal collects corrections and resumes the graph
through `POST /review/{extraction_id}`.

## Sample data

The repository ships:

- `Task/Binder2_Redacted.pdf` — a 99-page image-based statement bundle
  that exercises the OCR fallback. Cold-start OCR on this file takes
  roughly five minutes with the bundled Tesseract engine; subsequent
  requests reuse the result via the LangGraph checkpointer. Pass the
  pre-extracted OCR text via `ocr_text` to skip OCR entirely.
- `Task/ixonia_binder2_ocr.txt` — the pre-extracted OCR text for the
  bundle, used by the bundled eval.
- `Task/task.md` — the original brief.

The bundle contains 10 statement periods; the etalon totals and
transaction counts in `Task/` are reproduced exactly by the extraction
pipeline.

## Development

CI runs the gates below on every PR; run them locally before pushing.

```bash
# Backend
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q

# Frontend
cd frontend
pnpm biome check .
pnpm tsc --noEmit
```

| Tool         | Purpose                       | Pass criterion         |
|--------------|-------------------------------|------------------------|
| `ruff check` | Lint (`E`, `F`, `I`, `B`, …)  | Zero diagnostics       |
| `ruff format`| Formatter                     | No reformat needed     |
| `mypy`       | Strict type check on `src/`   | Zero issues            |
| `pytest`     | Unit + graph tests            | All green              |
| `biome`      | Frontend lint + format        | Zero diagnostics       |
| `tsc`        | Frontend type check           | Zero diagnostics       |

## Repository layout

```
src/
├── api/            FastAPI app factory + HTTP routers + logging
│   ├── main.py     Application factory; mounts the routers; CORS;
│   │               lifespan that compiles the graph and opens the saver.
│   ├── routers/    /extract, /extract/stream, /pending_review, /review
│   ├── pricing.py  Frozen model-price table; cumulative cost reducer.
│   └── reviews.py  Pending-reviews SQLite store.
├── graph/          LangGraph wiring
│   ├── state.py    GraphState TypedDict and Annotated reducers.
│   ├── builder.py  Node and edge wiring; Send fan-out from split_periods.
│   └── checkpointer.py  Async sqlite / memory checkpointer factory.
├── nodes/          Per-step graph nodes
│   ├── ingest.py            PDF → text (pdfplumber → pypdf → OCR fallback)
│   ├── split_periods.py     Deterministic regex-driven splitter.
│   ├── classify_layout.py   Haiku-4.5 layout classifier per chunk.
│   ├── extract_account.py
│   ├── extract_summary.py
│   ├── extract_transactions.py  Sonnet-4.6 with prompt caching.
│   ├── merge_state.py       Reducer join point.
│   ├── verifier.py          Deterministic C1-C6 checks.
│   ├── reconcile.py         Pure-Python decimal reconciliation.
│   ├── critic_loop.py       Hint-driven retry router.
│   ├── apply_critic_hint.py Re-dispatch one extractor for one chunk.
│   ├── apply_human_corrections.py
│   ├── await_review.py      interrupt() for HITL.
│   └── finalize.py          Stitch per-chunk results into ExtractResult.
├── models/         Pydantic v2 value objects.
├── prompts/        Versioned Markdown prompts loaded by name.
└── evals/          Dataset + scorers + CLI runner.

frontend/           Vite + React 19 + TypeScript SPA (Biome formatter).
infra/              Dockerfile (api), Dockerfile.frontend, docker-compose.yml,
                    dokploy.json, nginx.conf.
tests/              pytest suite mirroring src/ layout.
Task/               Bundled sample PDF, OCR text, and original brief.
```

## License

MIT — see `pyproject.toml` for the license metadata.

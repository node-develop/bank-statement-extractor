# bank-statement-analizer

`bank-statement-analizer` is an HTTP service that ingests a bank-statement PDF
and returns structured `{account, summary, transactions}` JSON, one block per
statement period. Extraction is driven by a LangGraph pipeline that calls
Anthropic Claude (Haiku 4.5 for routing/classification, Sonnet 4.6 for
transaction extraction); a pure-Python reconciliation step verifies that
`beginning + Σdeposits − Σwithdrawals = ending` within $0.01 for each period.
A small Vite + React + TypeScript SPA drives the upload flow and renders the
result.

## Features

- Multi-period statements: a single PDF can carry many statement cycles; each
  period is extracted and reconciled independently.
- Per-period reconciliation with a fixed `Decimal("0.01")` tolerance. Failed
  reconciliation is surfaced explicitly (`reconciled: false`, `delta`,
  `notes[]`) rather than averaged away.
- Server-side OCR fallback for image-based PDFs. The ingest node prefers
  Azure Document Intelligence when `AZURE_DI_ENDPOINT` and `AZURE_DI_KEY`
  are set, otherwise falls back to `ocrmypdf` (Tesseract). Callers can also
  bypass OCR entirely by uploading a companion `.txt` file.
- Deterministic verifier (C1-C6 structural checks) plus a Haiku-4.5 critic
  that proposes targeted re-extractions for suspect periods.
- Human-in-the-loop pause via LangGraph's `interrupt()` — when too many
  suspects survive or the LLM cost cap is hit, the run pauses and exposes
  a pending-review record that the frontend resolves through a dedicated
  review endpoint.
- SSE progress streaming on `POST /extract/stream` for live per-node updates
  in the UI.
- Optional LangSmith tracing for every graph run.
- All monetary values are `decimal.Decimal`; the wire schema serializes them
  as quoted JSON strings quantized to two decimal places.

## Architecture overview

A single PDF may contain multiple statement periods. The graph splits the raw
text into one `PeriodChunk` per period and fans the four extractors out in
parallel via LangGraph's `Send` API. A deterministic verifier inspects the
merged state, and a router decides whether to reconcile, retry through the
critic loop, or pause for human review.

```
                                START
                                  │
                                  ▼
                               ingest                (pdfplumber → pypdf
                                  │                   → ocrmypdf/Azure DI
                                  ▼                   fallback)
                            split_periods            (deterministic regex)
                                  │
                  ┌───────────────┼──────── Send (one per chunk × 4) ────────┐
                  ▼               ▼               ▼                          ▼
          classify_layout   extract_account   extract_summary    extract_transactions
                  └───────────────┴───────────────┴──────────┬───────────────┘
                                                             ▼
                                                       merge_state
                                                             │
                                                             ▼
                                                         verifier            (C1-C6 checks)
                                                             │
                                            ┌────────────────┼────────────────┐
                                            ▼                ▼                ▼
                                       reconcile          critic         await_review
                                            │                │                │
                                            │                ▼                ▼
                                            │        apply_critic_hint    (interrupt;
                                            │                │             resume via
                                            │                ▼             POST /review)
                                            │           [Send loop]            │
                                            │                                  │
                                            ▼                                  ▼
                                       finalize ◄────────────────────────── finalize
                                            │
                                            ▼
                                           END
```

- Reducers (`operator.add`) merge the per-period results emitted by every
  parallel branch back into list-shaped state.
- LangGraph's SQLite checkpointer persists state between steps so the HITL
  interrupt can resume cleanly.
- A cumulative cost reducer enforces a hard per-request ceiling
  (`BSA_COST_CAP_USD`, default $5.00); when crossed, the router skips the
  critic and routes to `await_review`.

## Tech stack

- Python 3.13+ (`pyproject.toml` declares 3.14; the Docker image uses
  `python:3.14-slim`).
- FastAPI + uvicorn, multipart upload via `python-multipart`.
- LangGraph 1.0+, LangChain, LangSmith.
- Anthropic Claude — Haiku 4.5 for classification / routing / critic,
  Sonnet 4.6 for transaction extraction.
- `pdfplumber` (primary), `pypdf` (fallback), `ocrmypdf` + Tesseract for
  image-based PDFs, optional Azure Document Intelligence.
- `decimal.Decimal` for every monetary value; epsilon = `Decimal("0.01")`.
- Frontend: Vite + React 19 + TypeScript, formatted with Biome.
- Deploy: Docker (multi-stage), Dokploy 0.29.
- Dependency manager: `uv`.

## Quick start

### Local development

```bash
git clone <repo>
cd bank-statement-analizer
cp .env.example .env       # then fill in your keys
uv sync --extra dev
uv run uvicorn src.api.main:app --reload     # http://localhost:8000
# in another terminal
cd frontend && pnpm install && pnpm dev      # http://localhost:5173
```

### Docker Compose

```bash
cp .env.example .env       # fill in keys
docker compose -f infra/docker-compose.yml up --build
```

The compose stack publishes the API on port `8000` and an nginx-served
frontend on port `80`. A named volume (`bsa_data`) persists the LangGraph
SQLite checkpoint between restarts.

### Eval on the bundled Ixonia sample

```bash
uv run python -m src.evals.run \
    --statement Task/Binder2_Redacted.pdf \
    --txt Task/ixonia_binder2_ocr.txt
```

The bundled etalon covers 10 statement periods; the runner asserts exact-match
on every summary field and on transaction counts.

## HTTP API

- `GET  /healthz` — liveness probe; returns `{"status":"ok"}` as long as the
  process is up.
- `GET  /readyz` — readiness probe; returns 503 until `ANTHROPIC_API_KEY` is
  present and the graph has been compiled.
- `POST /extract` — multipart/form-data with `file` (PDF) and optional
  `ocr_text` (txt). Maximum upload size 80 MB for the PDF and 5 MB for the
  OCR companion. Returns an `ExtractResult` JSON on success (HTTP 200), 413
  on oversize, 415 on a non-PDF content type, 422 on an unreadable PDF.
  All monetary fields are quoted JSON strings (e.g. `"597068.70"`) to
  preserve `Decimal` precision — clients should parse them with a decimal
  library (`Decimal` in Python, `decimal.js` in JavaScript).
- `POST /extract/stream` — same contract as `/extract`, but the response is
  an `text/event-stream` of per-node progress events; the body of the final
  event carries the assembled `ExtractResult`.
- `GET  /pending_review`, `GET /review/{extraction_id}`,
  `POST /review/{extraction_id}` — human-in-the-loop endpoints used by the
  frontend's review modal to resume a paused extraction with corrections.

Example:

```bash
curl -F "file=@Task/Binder2_Redacted.pdf;type=application/pdf" \
     -F "ocr_text=@Task/ixonia_binder2_ocr.txt;type=text/plain" \
     http://localhost:8000/extract
```

## Configuration (.env)

Copy `.env.example` to `.env` and fill in the values you need. The required
variable is `ANTHROPIC_API_KEY`; everything else has sensible defaults. The
variables fall into five groups:

- Model API keys — `ANTHROPIC_API_KEY` is required.
- LangSmith tracing — optional; enables LLM call traces and prompt-cache
  inspection in https://smith.langchain.com/.
- CORS — `FRONTEND_ORIGIN` controls which origin the API accepts.
- OCR engine selection — when both `AZURE_DI_ENDPOINT` and `AZURE_DI_KEY`
  are set the ingest node prefers Azure Document Intelligence; otherwise
  it falls back to the bundled Tesseract via `ocrmypdf`.
- Checkpointer — `LANGGRAPH_CHECKPOINTER` defaults to `sqlite` with the
  database path at `LANGGRAPH_SQLITE_PATH`.

See `.env.example` for the full list with inline comments.

## Reconciliation contract

For every period the service computes:

```
beginning_balance + Σdeposits − Σwithdrawals == ending_balance  ± $0.01
```

When the invariant fails the response carries `reconciled: false` together
with the signed `delta` and a `notes[]` list explaining which sub-check
diverged (totals, counts, or balance equation). Numbers are never silently
averaged or corrected.

If the deterministic verifier finds 1-3 suspect periods after the first
extraction pass and the cost cap has not been hit, the graph runs the critic
loop (up to two retries) to re-extract problematic chunks with targeted
hints. Beyond that threshold — or when the cumulative LLM cost exceeds
`BSA_COST_CAP_USD` — the graph pauses via LangGraph `interrupt()` and the API
returns a partial `ExtractResult` plus a `pending_review` payload. The
frontend's review modal collects human corrections and resumes the graph
through `POST /review/{extraction_id}`.

## Sample data

The repository ships:

- `Task/Binder2_Redacted.pdf` — a 99-page image-based statement bundle that
  exercises the OCR fallback. Cold-start OCR on this file takes roughly five
  minutes with the bundled Tesseract engine; subsequent requests reuse the
  result via the LangGraph checkpointer.
- `Task/ixonia_binder2_ocr.txt` — the pre-extracted OCR text for the same
  bundle. Passing it as the `ocr_text` field on `/extract` skips the OCR
  pass entirely and is what the bundled eval uses.

The bundle contains 10 statement periods; the etalon totals and transaction
counts in `Task/` are reproduced exactly by the extraction pipeline.

## Development

Run the same gates that CI runs:

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest -q
cd frontend && pnpm biome check . && pnpm tsc --noEmit
```

## Repository layout

- `src/api/` — FastAPI app factory and HTTP routers (`extract`,
  `extract/stream`, `pending_review`, health probes).
- `src/graph/` — LangGraph `GraphState`, builder, checkpointer factories.
- `src/nodes/` — individual graph nodes: `ingest`, `split_periods`,
  `classify_layout`, `extract_account`, `extract_summary`,
  `extract_transactions`, `merge_state`, `verifier`, `reconcile`,
  `critic_loop`, `apply_critic_hint`, `await_review`, `finalize`.
- `src/models/` — Pydantic v2 value objects (`Account`, `Summary`,
  `Transaction`, `Reconciliation`, `ExtractResult`, …).
- `src/prompts/` — versioned prompt templates loaded by name from Markdown.
- `src/evals/` — evaluation harness, datasets, and scorers.
- `frontend/` — Vite + React 19 + TypeScript SPA.
- `infra/` — Dockerfile, `docker-compose.yml`, Dokploy manifest.
- `tests/` — pytest suite.
- `Task/` — bundled sample PDF, pre-extracted OCR text, and the original
  brief. Treat as read-only.

## License

MIT — see `pyproject.toml` for the license metadata.

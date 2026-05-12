# Runbook — how to drive development

This is a **paste-and-run** script for taking `bank-statement-analizer`
from scaffolding to a working `extract()` that reconciles on Ixonia and
generalizes to unseen banks. Each phase names the subagent to invoke,
the exact prompt to paste, and the acceptance criterion to verify before
moving on. Don't skip phases — later ones assume earlier ones.

> Subagents are defined in `.claude/agents/*.md`. In Claude Code, invoke a
> subagent by phrasing the prompt as `Use the <name> subagent to ...` or
> via the `Task` tool selector. Each subagent has its own model and tool
> allow-list — don't second-guess that.

## Phase 0 — local environment

One-time host setup. Skip if you've already done it.

```bash
# Tools
brew install uv pnpm jq         # macOS; equivalents on Linux
# Docker Desktop or colima for Dokploy compose

# Plugins (Claude Code, run from anywhere)
# Superpowers skill pack (Obra) — extends our project-local skills.
/plugin marketplace add obra/superpowers
/plugin install superpowers@obra
# Reload to pick it up.
```

Environment variables (put in `~/.zshrc` or a `.envrc`, **never** commit):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export LANGSMITH_API_KEY=lsv2_...
export LANGSMITH_PROJECT=bank-statement-analizer-dev
export LANGSMITH_TRACING=true
export CONTEXT7_API_KEY=ctx7_...     # for mcp-context7
```

Project install:

```bash
cd /Users/izual/PycharmProjects/bank-statement-analizer
uv sync --extra dev
uv run uvicorn src.api.main:app --reload     # sanity: /healthz returns ok
```

**Open the project in Claude Code.** Session-start hook
(`.claude/hooks/session-start-context.sh`) will inject the Ixonia etalon
into the system prefix automatically.

**Acceptance:** `curl localhost:8000/healthz` → `{"status":"ok"}` and you
see "[bank-statement-analizer context]" in the session preamble.

---

## Phase 1 — domain models (`src/models/`)

**Subagent:** `langgraph-engineer`.

**Prompt:**

```
Use the langgraph-engineer subagent.

Implement `src/models/` per docs/architecture.md "State shape" section.
Required pydantic v2 models:

- RawStatement(pages: list[str], tables: list[list[list[str]]],
               ocr_text: str | None, sha256: str)
- PeriodChunk(chunk_id: str, header_line: int, period_start_hint: date,
              period_end_hint: date, pages: list[int],
              ocr_slice: tuple[int, int],
              account_hint_last4: str, is_account_transition: bool)
- LayoutLabel(chunk_id: str,
              layout: Literal["ixonia_business_basic","generic_us_bank","unknown"])
- Account(chunk_id: str, bank: str, account_last4: str,
          period: Period(start: date, end: date))
- Summary(chunk_id: str, beginning_balance: Decimal, ending_balance: Decimal,
          deposits_total: Decimal, deposits_count: int,
          withdrawals_total: Decimal, withdrawals_count: int)
- Transaction(chunk_id: str, date: date, description: str,
              deposit: Decimal | None, withdrawal: Decimal | None,
              balance_after: Decimal)
- Reconciliation(chunk_id: str, reconciled: bool, delta: Decimal,
                 expected_ending: Decimal, computed_ending: Decimal,
                 notes: list[str])
- PeriodResult(account, summary, transactions, reconciliation)
- ExtractResult(periods: list[PeriodResult],
                statement_sha256: str,
                langsmith_run_url: str | None)

Money fields use `Decimal`. Dates use `datetime.date`. JSON
serialization: Decimal → string with 2 decimals; date → ISO 8601.

Tests in `tests/test_models.py`:
- Decimal round-trips through JSON without precision loss.
- A Transaction with both deposit and withdrawal set raises ValidationError.
- A Summary where deposits_count != deposits_total / avg fails... no,
  drop that — we don't enforce counts here, reconcile does.
```

**Acceptance:** `uv run pytest tests/test_models.py -q` passes; `uv run mypy src/models` clean.

---

## Phase 2 — `split_periods` deterministic node

**Subagent:** `langgraph-engineer`.

**Prompt:**

```
Use the langgraph-engineer subagent.

Implement `src/nodes/split_periods.py`. This is PURE PYTHON, no LLM
(rule 5). Read docs/architecture.md "Ixonia regression fixture" table —
your code must produce a chunk per row.

Spec:
- Input: GraphState["raw"]: RawStatement (use raw.ocr_text, splitlines).
- Output: state delta {"period_chunks": list[PeriodChunk]}.
- Primary anchor regex: r"^Beginning Balance as of (\d{2})/01/(\d{4})$" .
- Closing anchor regex: r"^Ending Balance as of (\d{2})/(\d{2})/(\d{4})$" .
- Account number regex: r"^Account Number:\s*(?:XXXXXX)?(\d{4})$" —
  look back from the Beginning anchor up to 20 lines for this line.
- is_account_transition = True iff the matched line contains "XXXXXX".
- ocr_slice = (line_of_beginning_anchor, line_of_ending_anchor).
- chunk_id = f"{period_start.isoformat()}:{account_hint_last4}".
- On regex miss (count != expected, where expected is computed from the
  number of "BUSINESS BASIC PLUS CHK" headers found), DO NOT call an LLM.
  Append a specific error to state["errors"] and return whatever chunks
  you got. `finalize` will surface reconciled=false.

Regression fixture in `tests/nodes/test_split_periods.py`:
- Load Task/ixonia_binder2_ocr.txt (read-only).
- Build a RawStatement with ocr_text only.
- Assert len(chunks) == 10.
- Assert chunks[i].header_line matches [38, 1133, 2379, 3399, 4410,
  5297, 6280, 6620, 7591, 8632].
- Assert chunks[1].is_account_transition is True and chunks[1].account_hint_last4 == "4664".
- Assert chunks[6].account_hint_last4 == "4623".
```

**Acceptance:** all 10 anchors hit; transition flags correct; test green.

---

## Phase 3 — `ingest` node

**Subagent:** `langgraph-engineer`.

**Prompt:**

```
Use the langgraph-engineer subagent.

Implement `src/nodes/ingest.py` per the pdf-text-extraction skill
(.claude/skills/pdf-text-extraction/SKILL.md).

- pdfplumber primary, pypdf fallback.
- Compute sha256 of file bytes; populate raw.sha256.
- If txt_path given, raw.ocr_text = file.read_text(); else None.
- Source-selection policy is HERE: PDF text per page is primary; OCR is
  only consulted when pdfplumber returns empty/garbage for that page.
- Append any source-disagreement on non-empty pages to state["errors"].
- No tests need real PDFs in this phase; smoke-test against
  Task/Binder2_Redacted.pdf locally and assert pages > 90.
```

**Acceptance:** `python -c "from src.nodes.ingest import ingest; print(ingest({'pdf_path':'Task/Binder2_Redacted.pdf','txt_path':'Task/ixonia_binder2_ocr.txt'})['raw'].sha256)"` returns a 64-char hex.

---

## Phase 4 — prompt exemplars

**Subagent:** `parser-architect`.

**Prompt:**

```
Use the parser-architect subagent.

Create the prompt files under `src/prompts/`. Each is a Markdown file
with frontmatter `version: 1`, loaded by name from Python via
src/prompts/__init__.py (which langgraph-engineer will write next phase).

Files:
1. classify_layout.md  — Haiku 4.5 prompt; output one of
   {ixonia_business_basic, generic_us_bank, unknown}. Few-shot: one
   Ixonia header block, one generic Bank of America snippet (fabricated,
   no PII).

2. extract_account.md  — Sonnet 4.6 prompt; output Account model.
   Few-shot: the Ixonia account-number row + masked form.

3. extract_summary.md  — Sonnet 4.6 prompt; output Summary model.
   Few-shot: the "Balance Summary" block from Apr 2025.

4. extract_transactions.md — Sonnet 4.6 prompt; output list[Transaction].
   MUST include the running-balance-delta rule from
   docs/architecture.md "Domain invariants" item 1, verbatim — that is
   how the model assigns deposit vs withdrawal. Three few-shot rows for
   Ixonia: (a) single-line "Apr 01 AIRLINEHYD 2759/VENDOR PMT 1,809.28
   598,877.98", (b) multi-line MID ATLANTIC TR continuation,
   (c) check-only row "May 28 *40861 617.16". Stitch multi-line
   descriptions per invariant 3.

5. critic.md           — Haiku 4.5 prompt for critic_loop; given a
   reconciliation failure, output which extractor (account/summary/
   transactions) of which chunk_id to re-run with what targeted hint.

Cache discipline: stable instructions first, dynamic context last.
Mark stable prefix with cache_control: ephemeral in the calling code
(langgraph-engineer's job, not yours; just keep the layout cache-friendly).

Append an entry to docs/prompts.md for each file you create.
```

**Acceptance:** files exist; `docs/prompts.md` has 5 new entries; each
prompt < 1k tokens.

---

## Phase 5 — LLM extractor nodes

**Subagent:** `langgraph-engineer`.

**Prompt:**

```
Use the langgraph-engineer subagent. Before coding, call
mcp__context7__query-docs for "langchain_anthropic ChatAnthropic
structured output cache_control" to confirm current API.

Implement:

- src/prompts/__init__.py — `load_prompt(name: str, version: int = 1) -> str`
  reading from `src/prompts/{name}.md`, stripping frontmatter.

- src/nodes/classify_layout.py — Haiku 4.5, ChatAnthropic, structured
  output LayoutLabel. Wraps prompt with cache_control ephemeral on the
  stable prefix.
- src/nodes/extract_account.py — Sonnet 4.6, structured output Account.
- src/nodes/extract_summary.py — Sonnet 4.6, structured output Summary.
- src/nodes/extract_transactions.py — Sonnet 4.6, structured output
  list[Transaction]. Takes a single PeriodChunk via Send.

Each node takes a Send-payload of one chunk and returns a state delta
appending exactly one entry to the matching list (layouts/accounts/etc).
chunk_id is propagated to every result so `merge_state` can stitch.

Tests in tests/nodes/test_extractors.py: mock ChatAnthropic with
LangChain's FakeListLLM or respx; assert structured output round-trips.
```

**Acceptance:** tests pass; mypy clean.

---

## Phase 6 — `reconcile` + `critic_loop`

**Subagent:** `reconciler-engineer`.

**Prompt:**

```
Use the reconciler-engineer subagent.

Implement `src/nodes/reconcile.py` per the reconciliation-math skill.
Three invariants, three notes[] entries on failure, never invent a
correction. Per-period.

Implement `src/nodes/critic_loop.py`:
- Triggered only when any reconciliation has reconciled=False.
- Reads docs/prompts/critic.md, calls Haiku 4.5, parses the structured
  hint, bumps state["retry_count"]. Max 2 retries.

Tests in tests/test_reconcile.py:
- test_reconcile_ixonia_apr_2025 (uses fixtures, not the real LLM)
- test_reconcile_off_by_one_cent
- test_reconcile_missing_transaction (count mismatch caught)
- test_reconcile_period_7_zero_net  — Sep 2024 / account 4623,
  Σdep == Σwd == 336565.07. Must reconcile.
```

**Acceptance:** all four tests green.

---

## Phase 7 — graph wiring

**Subagent:** `langgraph-engineer`.

**Prompt:**

```
Use the langgraph-engineer subagent. Pull current docs via
mcp__context7__query-docs for "langgraph Send conditional edges
StateGraph compile checkpointer".

Implement `src/graph/state.py` (the TypedDict from docs/architecture.md),
`src/graph/builder.py` (wires all nodes; Send fan-out from
split_periods to classify_layout + extract_account + extract_summary +
extract_transactions per PeriodChunk; merge_state join; conditional edge
from reconcile to critic_loop when any reconciliation failed and
retry_count < 2; otherwise to finalize), `src/graph/checkpointer.py`
(SQLite default, Postgres via DATABASE_URL), `src/nodes/finalize.py`
(assemble ExtractResult).

End-to-end test tests/test_graph_end_to_end.py: invoke build_graph()
on Task/Binder2_Redacted.pdf with a mocked Anthropic returning the
etalon for every chunk; assert all 10 periods present and reconciled.
```

**Acceptance:** mock-driven E2E passes; LangSmith run shows 10 trace
trees when run with a real key.

---

## Phase 8 — API endpoint

**Subagent:** `fastapi-engineer`.

**Prompt:**

```
Use the fastapi-engineer subagent.

Implement `src/api/routers/extract.py` per the fastapi-multipart-upload
skill. Replace the placeholder in src/api/main.py with the app factory
that mounts the router, configures CORS, and sets up structlog/json
logging in production.

Tests in tests/api/:
- test_extract_happy_path (mocks the graph; asserts 200 + etalon for Apr 2025)
- test_extract_reject_non_pdf (415)
- test_extract_too_large (413)
- test_readyz_503_without_key
```

**Acceptance:** `uv run pytest tests/api -q` green; `curl -F file=@Task/Binder2_Redacted.pdf localhost:8000/extract` (with real keys) returns reconciled JSON for Apr 2025.

---

## Phase 9 — frontend

**Subagent:** `react-engineer`.

**Prompt:**

```
Use the react-engineer subagent.

Scaffold `frontend/` per the react-upload-form-vite skill. Single page,
single file input, JSON viewer, reconciliation banner. Mirror Python
models in frontend/src/types.ts.

After: `cd frontend && pnpm install && pnpm dev` shows the form, and
uploading Task/Binder2_Redacted.pdf to a running API renders the
result.
```

**Acceptance:** `pnpm tsc --noEmit` clean; `pnpm biome check .` clean.

---

## Phase 10 — evaluation

**Subagent:** `evaluator`.

**Prompt:**

```
Use the evaluator subagent.

Build src/evals/datasets/ixonia.jsonl from docs/ixonia-etalon.md
(one example per period: inputs = pdf_path/txt_path/period_start;
outputs = the etalon summary + reconciled=True). Build src/evals/run.py
that invokes the graph for each example and scores against the etalon.

Run on Task/Binder2_Redacted.pdf. Write the report to
src/evals/reports/<UTC>.md. Fail loud on any regression vs. the etalon.
```

**Acceptance:** all 10 periods reconciled in the report; summary fields
exact-match; transaction counts equal etalon.

---

## Phase 11 — deploy

**Subagent:** `dokploy-deployer`.

**Prompt:**

```
Use the dokploy-deployer subagent.

Verify `infra/Dockerfile` builds: `docker build -f infra/Dockerfile -t bsa-api .`.
Verify compose: `docker compose -f infra/docker-compose.yml up --build`.
Confirm /healthz and /readyz respond from inside the container.
Document any Dokploy 0.29 manifest tweaks discovered during the local
container test in infra/dokploy.json.
```

**Acceptance:** image < 500 MB; healthcheck green within 30 s; manifest
loads in Dokploy UI without warnings.

---

## Phase 12 — critic review

**Subagent:** `critic`.

**Prompt:**

```
Use the critic subagent.

Review the full diff vs. main. Score against each of the 12 rules in
CLAUDE.md. Re-run lint + mypy + pytest yourself; do not trust prior
claims. Produce the JSON verdict per .claude/agents/critic.md output
contract. If any finding is HIGH severity, name the agent to fix it.
```

**Acceptance:** verdict == "approve" or you address the findings and
re-run the critic until it approves.

---

## After Phase 12 — held-out evaluation

Drop one unseen-bank PDF + OCR under `src/evals/fixtures/<bank>/`. Run
`parser-architect` with:

```
Use the parser-architect subagent.

Add support for `<bank_slug>` from src/evals/fixtures/<bank_slug>/sample.pdf
(+ sample.txt if present). Hand off to evaluator when done. Target: same
reconciliation rate as Ixonia (100%) without touching any Python file
besides src/nodes/classify_layout.py's allow-list.
```

That phase repeats for each new bank. The test-task grading requires
≥ 2 unseen banks reconciling, so plan for two passes.

## Token-budget hygiene

Every subagent call costs you. Rough budgets per phase:

| Phase | Budget |
|-------|--------|
| 1     | 8k     |
| 2     | 12k (includes a full read of the OCR fixture in test) |
| 3     | 6k     |
| 4     | 15k (prompt exemplars are token-heavy)               |
| 5     | 12k    |
| 6     | 8k     |
| 7     | 15k    |
| 8     | 8k     |
| 9     | 10k    |
| 10    | 8k     |
| 11    | 6k     |
| 12    | 12k    |
| **Total** | **~120k** |

If any phase blows past 1.5× its budget, stop and recap with the user
before continuing (rule 10).

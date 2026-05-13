# PRD — Cost reduction + Verifier agent + Human-in-the-loop

**Document version:** 1.0
**Date:** 2026-05-13
**Owner:** dev@artka.dev
**Implementation target:** 5 phases, ≈ 830 LoC, ≈ 3 sessions at 30 k token budget each
**Implementation order:** P1 → P2 → P3 → (P4 ∥ P5)
**Companion docs:** `docs/plan-cost-and-verifier.md` (rationale + cost math),
`docs/architecture.md` (graph topology), `CLAUDE.md` (12 rules), `docs/runbook.md` (phase pattern).

---

## 0 · Problem statement

Today (commit `d5d3392`) the extraction pipeline:

1. **Reconciles 9/10 Ixonia periods** at exact-match on balances + tx counts;
   period_08 fails with `delta=$2 425` because 1-2 rows have wrong amounts.
2. **Costs $2.55 per full Ixonia run** (10 periods, 869 transactions, 5:42 wall-clock).
   87 % of that goes to `extract_transactions` output tokens.
3. **Silently guesses** when extraction is imperfect. The critic logs a hint into
   `errors[]`, but the user has no row-level visibility and no way to correct.

This PRD fixes all three: ~57 % cost cut, deterministic per-row verification, and
a human-in-the-loop escalation path with structured row corrections.

---

## 1 · Current state (immutable contracts you build on)

### 1.1 Repo layout (only the relevant parts)

```
src/
├── api/
│   ├── main.py                  # FastAPI app factory + lifespan + /healthz + /readyz
│   ├── logging.py               # get_logger(name) — DO NOT use print
│   └── routers/extract.py       # POST /extract — multipart, 80 MB cap
├── graph/
│   ├── state.py                 # GraphState TypedDict + reducers
│   ├── checkpointer.py          # build_checkpointer (sync) + build_async_checkpointer (async, AsyncSqliteSaver)
│   └── builder.py               # build_graph(checkpointer) — Send fan-out + critic loop + finalize
├── models/__init__.py           # Pydantic v2: Account / Summary / Transaction / Reconciliation / PeriodResult / ExtractResult
├── nodes/
│   ├── ingest.py                # pdfplumber → pypdf fallback; sha256
│   ├── split_periods.py         # deterministic regex; emits PeriodChunk list
│   ├── classify_layout.py       # Haiku 4.5 → LayoutLabel
│   ├── extract_account.py       # Sonnet 4.6 → Account (uses chunk.account_hint_last4 override)
│   ├── extract_summary.py       # Sonnet 4.6 → Summary
│   ├── extract_transactions.py  # Sonnet 4.6 → list[Transaction]; max_tokens=32 000
│   ├── merge_state.py           # join after fan-out
│   ├── reconcile.py             # pure Decimal math; count=0 sentinel = "unknown"
│   ├── critic_loop.py           # Haiku 4.5 → CriticHint; bumps retry_count; max 2 retries
│   └── finalize.py              # builds ExtractResult; raises on missing chunk_id
├── prompts/                     # *.md with frontmatter; load_prompt(name, version=1)
└── evals/                       # ixonia.jsonl dataset + scorers.py + run.py
tests/fixtures/                  # 5 holdout statements + ground_truth_all.json
infra/Dockerfile, docker-compose.yml, dokploy.json, nginx.conf
frontend/                        # Vite + React 19 + TS + biome
```

### 1.2 Models you MUST extend (do not break existing fields)

```python
# src/models/__init__.py — existing
class Transaction(BaseModel):
    chunk_id: str
    date: date
    description: str
    amount: Decimal               # non-negative; sign in `direction`
    direction: Literal["credit", "debit"]
    running_balance: Decimal | None = None
```

### 1.3 Graph topology (current)

```
START → ingest → split_periods → [Send×4 per chunk] →
        classify_layout / extract_account / extract_summary / extract_transactions →
        merge_state → reconcile →
        should_run_critic ─┬→ critic → merge_state (loop ≤ 2)
                           └→ finalize → END
```

### 1.4 LangGraph primitives you will use (verified via context7
`/websites/langchain_oss_python_langgraph` — 2026-05-13)

- `from langgraph.types import interrupt, Command` — pause + resume.
- `interrupt(payload)` pauses the graph; payload is JSON-serialisable;
  appears at `result["__interrupt__"]` as `[Interrupt(value=...)]`.
- `Command(resume=value)` resumes; `value` becomes the return of the
  paused `interrupt(...)` call.
- `Command(resume={interrupt_id: value, ...})` resumes multiple parallel
  interrupts in one call.
- Requirement: a checkpointer **and** a stable `thread_id` in
  `config={"configurable": {"thread_id": "..."}}`. We already have
  `AsyncSqliteSaver` wired in the lifespan.

---

## 2 · Phase 1 — Cost cut (target -50 % on $0.05; -57 % on $2.55)

### 2.1 Files to change

| File | Change |
|---|---|
| `src/nodes/extract_account.py` | `ChatAnthropic(model="claude-sonnet-4-6", max_tokens=4096)` → `model="claude-haiku-4-5", max_tokens=1024` |
| `src/nodes/extract_summary.py` | same |
| `src/nodes/extract_transactions.py` | **KEEP Sonnet 4.6, max_tokens=32 000** — do not touch |
| `src/nodes/extract_transactions.py` | strip `chunk_id` from `_TransactionList` schema sent to LLM; reinject server-side per row |
| `src/prompts/extract_account.md` | rebalance exemplars for Haiku (smaller, sharper) |
| `src/prompts/extract_summary.md` | same |

### 2.2 chunk_id stripping — concrete change

Inside `src/nodes/extract_transactions.py`, the structured-output schema today
forces the LLM to emit `chunk_id` on every row (~30 tokens × 192 rows = 5 760
wasted output tokens for Ixonia period_01). Replace the inner schema with a
"LLM-facing" variant that omits `chunk_id`, then map back to `Transaction`
server-side:

```python
class _TransactionRow(BaseModel):  # LLM-facing — no chunk_id
    date: date
    description: str
    amount: Decimal
    direction: Literal["credit", "debit"]
    running_balance: Decimal | None = None

class _TransactionList(BaseModel):
    transactions: list[_TransactionRow]

# after LLM call:
tx_list = [
    Transaction(chunk_id=chunk.chunk_id, **row.model_dump())
    for row in raw_result.transactions
]
```

### 2.3 Acceptance criteria

- `uv run pytest -q` — all 117 tests still pass; **update tests that hard-code
  Sonnet model names** (look in `tests/nodes/test_extract_account.py` and
  `tests/nodes/test_extract_summary.py` — there are no model-name assertions
  today but verify cache_discipline tests pass).
- `python3 tests/fixtures/run_all.py` — 4/5 fixtures still fully match (we
  accept the same baseline as today; the goal is cost cut, not accuracy gain).
- LangSmith trace of Ixonia run shows `extract_account` + `extract_summary`
  using `claude-haiku-4-5` (verified via `r.extra.invocation_params.model_name`).
- Cost per Ixonia run drops to **≤ $1.30** (measured via the LangSmith script
  used at PRD-write time — paginate `list_runs(... limit=100)` and sum
  `total_cost` per trace).

### 2.4 Subagent

`langgraph-engineer` owns the node changes. `parser-architect` may tune the
exemplars in `src/prompts/extract_account.md` + `extract_summary.md` if the
Haiku output regresses on the holdout fixtures.

### 2.5 Risk + rollback

If holdout accuracy drops, the rollback is one commit (revert the model swap).
Cost remains the dominant lever — even partial rollback (only `extract_summary`
on Haiku) gives ~25 % savings.

---

## 3 · Phase 2 — Verifier agent

### 3.1 New file: `src/nodes/verifier.py`

Runs **between** `extract_transactions` and `reconcile`. Pure Python deterministic
checks + an optional Haiku 4.5 second-opinion when running_balance is missing on
> 30 % of rows.

#### Schema

```python
# src/models/__init__.py — append new models

class Suspect(BaseModel):
    chunk_id: str
    row_index: int                # 0-based within the chunk's tx list
    code: Literal[
        "balance_chain_break",    # C1
        "date_order",             # C2
        "duplicate_row",          # C3
        "empty_description",      # C4
        "zero_amount",            # C5
        "summary_delta",          # C6
    ]
    reason: str                   # human-readable, ≤ 200 chars
    expected: str | None = None   # e.g. expected running_balance value
    actual: str | None = None

class Gap(BaseModel):
    chunk_id: str
    after_row_index: int          # gap appears between row N and N+1
    date_range: tuple[date, date]
    missing_amount: Decimal       # signed; positive = missing credit, negative = missing debit

class VerifierReport(BaseModel):
    chunk_id: str
    confidence: Decimal           # 0..1; 1.0 = all checks pass
    suspects: list[Suspect]
    gaps: list[Gap]
```

#### Six checks (deterministic, no LLM)

```python
EPSILON = Decimal("0.01")

def verify_chunk(
    summary: Summary, txs: list[Transaction]
) -> VerifierReport:
    suspects: list[Suspect] = []
    gaps: list[Gap] = []

    # ---- C1: running-balance chain ---------------------------------
    prev = summary.beginning_balance
    for i, tx in enumerate(txs):
        signed = tx.amount if tx.direction == "credit" else -tx.amount
        expected = prev + signed
        if tx.running_balance is not None and abs(tx.running_balance - expected) > EPSILON:
            suspects.append(Suspect(
                chunk_id=tx.chunk_id, row_index=i, code="balance_chain_break",
                reason="running_balance does not equal prev_balance + signed_amount",
                expected=str(expected),
                actual=str(tx.running_balance),
            ))
            # gap detection: actual - expected is the missing amount
            gaps.append(Gap(
                chunk_id=tx.chunk_id, after_row_index=i - 1,
                date_range=(txs[i-1].date if i > 0 else tx.date, tx.date),
                missing_amount=tx.running_balance - expected,
            ))
        prev = tx.running_balance if tx.running_balance is not None else expected

    # ---- C2: date monotonicity -------------------------------------
    for i in range(1, len(txs)):
        if txs[i].date < txs[i-1].date:
            suspects.append(Suspect(
                chunk_id=txs[i].chunk_id, row_index=i, code="date_order",
                reason=f"date {txs[i].date} earlier than prev {txs[i-1].date}",
            ))

    # ---- C3: duplicate (date, amount, direction) -------------------
    seen: dict[tuple, int] = {}
    for i, tx in enumerate(txs):
        key = (tx.date, tx.amount, tx.direction)
        if key in seen and txs[seen[key]].description == tx.description:
            suspects.append(Suspect(
                chunk_id=tx.chunk_id, row_index=i, code="duplicate_row",
                reason=f"identical row already seen at index {seen[key]}",
            ))
        seen[key] = i

    # ---- C4: empty / pseudo-row description ------------------------
    PSEUDO = {"BEGINNING BALANCE", "ENDING BALANCE", ""}
    for i, tx in enumerate(txs):
        if tx.description.strip().upper() in PSEUDO:
            suspects.append(Suspect(
                chunk_id=tx.chunk_id, row_index=i, code="empty_description",
                reason=f"description is empty or pseudo-row: {tx.description!r}",
            ))

    # ---- C5: zero amount -------------------------------------------
    for i, tx in enumerate(txs):
        if tx.amount == Decimal("0"):
            suspects.append(Suspect(
                chunk_id=tx.chunk_id, row_index=i, code="zero_amount",
                reason="amount is zero — likely a header/separator row",
            ))

    # ---- C6: pre-reconcile delta -----------------------------------
    credits_total = sum((t.amount for t in txs if t.direction == "credit"), Decimal("0"))
    debits_total = sum((t.amount for t in txs if t.direction == "debit"), Decimal("0"))
    computed_ending = summary.beginning_balance + credits_total - debits_total
    delta = summary.ending_balance - computed_ending
    if abs(delta) > EPSILON:
        # Identify the row most likely to be wrong: the FIRST row whose
        # running_balance breaks the chain.  If none breaks (or all are
        # None), point at row 0 with the global delta.
        breaker = None
        prev = summary.beginning_balance
        for i, tx in enumerate(txs):
            signed = tx.amount if tx.direction == "credit" else -tx.amount
            expected = prev + signed
            if tx.running_balance is not None and abs(tx.running_balance - expected) > EPSILON:
                breaker = i
                break
            prev = tx.running_balance if tx.running_balance is not None else expected
        suspects.append(Suspect(
            chunk_id=txs[0].chunk_id if txs else summary.chunk_id,
            row_index=breaker if breaker is not None else 0,
            code="summary_delta",
            reason=f"sum of rows differs from summary by {delta}",
            expected=str(summary.ending_balance),
            actual=str(computed_ending),
        ))

    confidence = Decimal("1") if not suspects else max(
        Decimal("0"),
        Decimal("1") - Decimal(len(suspects)) / Decimal(max(len(txs), 1)),
    )

    return VerifierReport(
        chunk_id=txs[0].chunk_id if txs else summary.chunk_id,
        confidence=confidence.quantize(Decimal("0.01")),
        suspects=suspects,
        gaps=gaps,
    )
```

#### Node signature

```python
def verifier(state: GraphState) -> dict:
    """Run C1-C6 on every (summary, transactions) pair grouped by chunk_id.
    Returns {"verifier_reports": [VerifierReport, ...]} — appended via a
    new `operator.add` reducer on GraphState.
    """
```

### 3.2 Unit tests — `tests/nodes/test_verifier.py`

One test per check (C1-C6) plus two integration tests:

- `test_verifier_clean_chain_passes` — Ixonia Apr-2025 etalon → confidence == 1.0,
  no suspects, no gaps.
- `test_verifier_broken_running_balance` — synth period_08-style mis-amount on
  row 5 → exactly 1 suspect with code `balance_chain_break`, gap with
  `missing_amount` matching the introduced error.
- `test_verifier_date_inversion` — swap rows 3 and 4 dates → 1 suspect `date_order`.
- `test_verifier_duplicate_row` — copy row 7 → suspect `duplicate_row`.
- `test_verifier_pseudo_row` — inject `description="BEGINNING BALANCE"` → suspect.
- `test_verifier_zero_amount` → suspect.
- `test_verifier_summary_delta` — sum-of-rows ≠ summary → suspect `summary_delta`
  with `breaker` set to first broken row (or 0 if all running_balance is None).
- `test_verifier_confidence` — N suspects on M-row chunk → confidence in (0, 1).

All tests use pure-Python synthetic data; **no LLM mocks needed** (verifier is
deterministic by design).

### 3.3 Acceptance criteria

- All 8 new tests pass.
- `python3 tests/fixtures/run_all.py` — Ixonia period_08 now emits the broken
  row in `errors[]` (or in a new `verifier_suspects[]` aggregator on
  ExtractResult — see §3.4).

### 3.4 Add to PeriodResult AND ExtractResult

```python
class PeriodResult(BaseModel):
    chunk_id: str
    account: Account
    summary: Summary
    transactions: list[Transaction]
    layout: str
    reconciliation: Reconciliation
    verifier: VerifierReport | None = None   # NEW — None if verifier didn't run

class PendingReview(BaseModel):
    """Surfaced on ExtractResult when the graph paused via interrupt()."""
    extraction_id: str           # uuid4 — used by the GET/POST /review/{id} routes
    reason: Literal[
        "suspects_exceeded",
        "cost_ceiling_exceeded",
        "retry_exhausted",
    ]
    suspect_count: int

class ExtractResult(BaseModel):
    """Top-level response returned from POST /extract."""
    periods: list[PeriodResult]
    statement_sha256: str
    langsmith_run_url: str | None = None
    errors: list[str] = Field(default_factory=list)
    pending_review: PendingReview | None = None   # NEW — None on the happy path
```

`finalize.py` reads `state["verifier_reports"]` and attaches the matching
report by `chunk_id` to each `PeriodResult`. The POST `/extract` handler
detects `result["__interrupt__"]` on the graph response and constructs the
top-level `pending_review` field from the API-layer side (which keeps graph
nodes free of API-layer imports — see §5.7 layer-boundary resolution).

Backward compatible: both new fields default to `None`.

### 3.5 Subagent

`reconciler-engineer` owns `src/nodes/verifier.py` — checks are pure Decimal
math, no LLM. `langgraph-engineer` owns the model addition and `finalize`
wiring.

---

## 4 · Phase 3 — Wire verifier into the graph

### 4.1 New edges — verifier runs BEFORE reconcile

The verifier is a **pre-check** that decides whether reconciliation is even
worth attempting. The plan doc (`docs/plan-cost-and-verifier.md:§3.1`) and the
LangGraph topology agree on this ordering:

```
extract_transactions → merge_state →
        verifier (NEW)
            │
            ▼
    route_after_verifier (NEW conditional)
        ├── all chunks: confidence == 1.0 AND no suspects → reconcile → finalize
        ├── 1 ≤ total_suspects ≤ 3 AND retry_count < 2  → critic (existing path)
        └── total_suspects > 3  OR  retry_count >= 2
                              OR  cumulative_cost_usd >= cap  → await_review (NEW)
```

Why **before** reconcile and not after:

- Verifier's C6 (`summary_delta`) computes `beginning + Σcredits − Σdebits`
  exactly the same way `reconcile` does. Running verifier first means the
  reconcile node only ever sees clean (suspect-free) chunks and its sole
  remaining role is to write the final `Reconciliation` record. If we ran
  verifier AFTER reconcile, C6 would duplicate work and we couldn't route
  to await_review without a reconciliation result that we already know is
  going to fail.
- The plan's intent is "no guessing": catch row-level breakage before
  reconcile decides reconciled=False, and route the broken chunks to
  critic-retry or human review with row-level detail.

`verifier` is a join node (runs once after `merge_state` has fan-in'd all
chunks). `await_review` is the HITL pause node (Phase 4).

### 4.2 Conditional edge — `route_after_verifier`

Place this helper in `src/nodes/critic_loop.py` alongside the existing
`should_run_critic` function. `HARD_COST_CAP_USD` lives in
`src/api/pricing.py` (next to the pricing table — see §8.1) and is imported
here:

```python
from src.api.pricing import HARD_COST_CAP_USD

def route_after_verifier(state: GraphState) -> str:
    reports = state.get("verifier_reports", [])
    total_suspects = sum(len(r.suspects) for r in reports)
    retry = state.get("retry_count", 0)
    cost_capped = state.get("cumulative_cost_usd", Decimal("0")) >= HARD_COST_CAP_USD

    if total_suspects == 0 and not cost_capped:
        return "reconcile"  # happy path, reconcile then finalize via existing wiring
    if cost_capped or total_suspects > 3 or retry >= 2:
        return "await_review"
    return "critic"          # retry path — see §4.2.1 for critic adaptation
```

Note: this function does NOT read `state["reconciliations"]` — reconciliation
hasn't run yet at this point in the new topology.

### 4.2.1 Critic node adaptation (CRITICAL — resolves critic GAP-A)

The existing `critic` node (`src/nodes/critic_loop.py:118-125`) reads
`state["reconciliations"]` and early-returns if empty. In the new topology
reconciliation has NOT run when critic is invoked from `route_after_verifier`,
so the existing implementation would silently no-op.

**Rewrite critic to consume `verifier_reports` instead.** Concrete change:

```python
# OLD (M2) — critic_loop.py around line 100-125
def critic(state: GraphState) -> dict:
    failed = [r for r in state.get("reconciliations", []) if not r.reconciled]
    if not failed:
        return {"errors": ["critic invoked but all periods reconciled"]}
    rec = failed[0]
    # ... call Haiku 4.5 with the failure context ...

# NEW (Phase 3) — same file, rewritten signature
def critic(state: GraphState) -> dict:
    reports_with_suspects = [
        r for r in state.get("verifier_reports", []) if r.suspects
    ]
    if not reports_with_suspects:
        return {"errors": ["critic invoked but no verifier suspects"]}
    report = reports_with_suspects[0]
    # ... call Haiku 4.5 with the verifier suspects context ...
```

The `critic.md` prompt (in `src/prompts/`) must also be updated to take
`VerifierReport` suspects instead of `Reconciliation` notes. The Haiku
output schema (`CriticHint`) stays the same — it still picks one extractor
to re-run.

**Critic exit edge:** after `critic`, route via a new edge back to a
`Send`-fan-out that re-runs ONLY the affected extractor for the affected
chunk_id (mirror of `apply_human_corrections` from §5.5, but the hint
comes from `pending_hint: CriticHint` rather than a human). After that
single retry, control returns to `merge_state` → `verifier` →
`route_after_verifier` for the second-pass decision.

```
critic → apply_critic_hint (Send → extract_*) → merge_state → verifier → route_after_verifier
```

This makes the loop bounded: retry_count is bumped each critic pass; after
2 retries `route_after_verifier` forces `await_review`.

### 4.2.2 `apply_critic_hint` node — full spec (resolves critic GAP-F)

**File path:** `src/nodes/apply_critic_hint.py` (NEW — add to §1.1 file
tree under `src/nodes/`).

**CriticHint schema:** already exists in M2 code at
`src/nodes/critic_loop.py:50-60`:

```python
class CriticHint(BaseModel):
    chunk_id: str
    extractor: Literal["extract_account", "extract_summary", "extract_transactions"]
    hint: str  # one-sentence steer for the rerun
```

**State key:** `pending_hint: NotRequired[Any]` already exists in
`GraphState` (M2 — typed `Any` to avoid circular import; runtime type is
`CriticHint`). No new state key needed.

**Function signature + body:**

```python
# src/nodes/apply_critic_hint.py
from typing import Any
from langgraph.types import Send

from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph
from src.models import PeriodChunk


def apply_critic_hint(state: GraphState) -> list[Send]:
    """Per critic GAP-F (Phase 3) — re-run ONE extractor for ONE chunk
    based on `state['pending_hint']` (set by the critic node).  Mirror of
    `apply_human_corrections` from §5.5 but for the bounded critic
    retry loop (max 2 retries enforced by `route_after_verifier`).
    """
    hint = state.get("pending_hint")
    if hint is None:
        # Defensive: no hint means critic produced nothing actionable.
        # Route directly to verifier with no re-extraction.
        return []

    # Find the chunk by hint.chunk_id
    chunks: list[PeriodChunk] = state["period_chunks"]
    target = next((c for c in chunks if c.chunk_id == hint.chunk_id), None)
    if target is None:
        return []  # silent skip; merge_state's invariant check catches it

    # Annotate the chunk text with the critic's natural-language hint.
    # Same dual-injection rule as apply_human_corrections (§5.5):
    # write to BOTH pdf_text AND ocr_slice so the extractor sees it
    # regardless of which source it prefers.
    hint_block = (
        f"## Critic hint (treat as ground truth; do not contradict)\n"
        f"- {hint.hint}\n\n"
        f"## Statement chunk\n\n"
    )
    annotated = target.model_copy(update={
        "pdf_text":   hint_block + target.pdf_text,
        "ocr_slice": (hint_block + target.ocr_slice) if target.ocr_slice is not None else None,
    })

    return [Send(hint.extractor, annotated)]
```

**Test requirement** — `tests/nodes/test_apply_critic_hint.py`:
- `test_apply_critic_hint_dispatches_one_send` — given a state with a
  CriticHint for chunk_01 / `extract_transactions`, returns exactly one
  `Send("extract_transactions", chunk)` with the hint block prepended to
  both `pdf_text` and `ocr_slice`.
- `test_apply_critic_hint_missing_hint_returns_empty` — pending_hint
  absent → returns `[]` (graph short-circuits to merge_state).
- `test_apply_critic_hint_unknown_chunk_returns_empty` — hint references
  a chunk_id not in state → returns `[]`.

**Owner:** `langgraph-engineer` (per §5.7 — graph nodes).

**§1.1 file-tree addition:** under `src/nodes/`, add `apply_critic_hint.py`
right before `apply_human_corrections.py` (alphabetical order would also
work). The Phase 3 commit creates both files.

### 4.3 GraphState additions (complete list — every new key has a reducer or NotRequired)

```python
class GraphState(TypedDict):
    # ... existing keys unchanged

    # Phase 2 — verifier reports, one per chunk_id (last-write-wins reducer)
    verifier_reports: Annotated[list[VerifierReport], _reduce_by_chunk_id]

    # Phase 4 — HITL state
    # Human corrections submitted via POST /review/{id}.
    # NotRequired (no reducer) → last-write-wins.  Each POST /review/{id}
    # call FULLY REPLACES the prior corrections list (per critic GAP-B:
    # API status machine returns 409 if status != 'pending', so multiple
    # POSTs for the same extraction_id are impossible by design — but if
    # the graph re-pauses after a resume, the API issues a NEW extraction_id
    # with a NEW thread_id, so accumulation never happens within one
    # thread).
    human_corrections: NotRequired[list["TransactionCorrection"]]

    # NotRequired bool, last-write-wins.  True if user opts to bypass re-extraction.
    force_resume: NotRequired[bool]

    # NotRequired bool, last-write-wins.  Set by await_review when interrupt() fires.
    pending_review: NotRequired[bool]

    # JSON-serialisable payload surfaced to the human via interrupt().
    review_payload: NotRequired[dict]

    # Phase 4 — cost ceiling.  operator.add on Decimal is well-defined (associative).
    # Initial state MUST set this to Decimal("0") at both invocation sites
    # (see §8.2 for the explicit file list).
    cumulative_cost_usd: Annotated[Decimal, operator.add]
```

### 4.4 Initial-state additions (CRITICAL — both invocation sites)

`cumulative_cost_usd` MUST be initialised to `Decimal("0")` in BOTH initial
state construction sites, or LangGraph's reducer raises `KeyError` on the
first node that adds to it:

| File | Function | Line (approx) | Add to dict |
|---|---|---:|---|
| `src/api/routers/extract.py` | `extract` (POST handler) | 131-141 | `"cumulative_cost_usd": Decimal("0")` |
| `src/graph/builder.py` | `run_extract` convenience | 238-246 | `"cumulative_cost_usd": Decimal("0")` |
| `src/api/routers/extract.py` | (no other places) | — | — |

Tests creating GraphState directly (e.g. `tests/test_graph_end_to_end.py`)
also need the key — search for the dict literal `"retry_count": 0,` and add
the cumulative-cost initialiser next to it.

### 4.5 Acceptance criteria

- **New E2E test** `tests/test_verifier_e2e.py`:
  - `test_verifier_routes_one_broken_row_to_critic` — synthetic period with
    exactly 1 amount off by $50 → C1 fires once + C6 fires once = 2 suspects
    → routes to `critic` (NOT `await_review`, since 2 ≤ 3). Asserts
    `__interrupt__` is NOT in result.
  - `test_verifier_routes_many_broken_rows_to_review` — synthetic period
    with 5 amount mismatches → 5+ suspects → routes to `await_review` →
    `__interrupt__` present with the payload containing all 5 suspects.
  - `test_verifier_routes_cost_cap_to_review` — start state with
    `cumulative_cost_usd=Decimal("4.99")`, set
    `BSA_COST_CAP_USD=5.00`; after one extra LLM call → `await_review`
    with `reason="cost_ceiling_exceeded"`.
- **Existing tests adapted:**
  - `test_e2e_single_period_reconciles` — still passes (verifier reports
    confidence=1.0, route to reconcile, all good).
  - `test_e2e_critic_runs_on_failure` — verifier now precedes critic. The
    test should mock the extractor to produce 1-3 suspects, assert critic
    is invoked, and assert the final result has `reconciled=False` with
    structured suspects on `PeriodResult.verifier`.
- **Update `docs/architecture.md`** (this is part of Phase 3 done-definition):
  rewrite the "Graph topology" diagram (around lines 15-33) to show
  `merge_state → verifier → route_after_verifier → {reconcile | critic | await_review}`.
  Without this update, future agents will read the stale topology and wire
  incorrectly.

### 4.5 Subagent

`langgraph-engineer` — graph wiring, conditional edges, GraphState changes.

---

## 5 · Phase 4 — Human-in-the-loop API

### 5.1 New file: `src/api/reviews.py`

```python
"""Application-level index for pending reviews — separate from the
LangGraph checkpointer database (per PRD §D3 decision)."""
import sqlite3
from pathlib import Path
from datetime import datetime, UTC
from contextlib import contextmanager

_REVIEWS_DB_PATH = Path(os.environ.get("REVIEWS_DB_PATH", "/app/data/reviews.sqlite"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_reviews (
    extraction_id     TEXT PRIMARY KEY,             -- uuid4 from API endpoint
    thread_id         TEXT NOT NULL,                -- LangGraph thread_id
    statement_sha256  TEXT NOT NULL,
    created_at        TEXT NOT NULL,                -- ISO 8601 UTC
    status            TEXT NOT NULL CHECK(status IN ('pending', 'in_review', 'resolved', 'aborted')),
    suspect_count     INTEGER NOT NULL DEFAULT 0,
    reason            TEXT,                         -- 'suspects_exceeded' | 'cost_ceiling_exceeded' | 'retry_exhausted'
    review_payload    TEXT NOT NULL                 -- JSON: full ExtractResult-so-far + suspects + chunk excerpts
);
CREATE INDEX IF NOT EXISTS idx_pending_reviews_status ON pending_reviews(status);
CREATE INDEX IF NOT EXISTS idx_pending_reviews_created ON pending_reviews(created_at);
"""

def init_reviews_db() -> None: ...
def insert_pending(extraction_id, thread_id, ...) -> None: ...
def list_pending(limit=50) -> list[dict]: ...
def get_review(extraction_id) -> dict | None: ...
def mark_in_review(extraction_id) -> None: ...
def mark_resolved(extraction_id) -> None: ...
```

The `reviews.sqlite` file lives in the same persisted Docker volume
(`/app/data`) as the checkpointer's `graph.sqlite` but is a separate file.

#### Initialisation call site (CRITICAL)

`init_reviews_db()` MUST be called once at process startup from the FastAPI
lifespan in `src/api/main.py`:

```python
# src/api/main.py — _lifespan (extend the existing function)
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    saver, teardown = await build_async_checkpointer()
    app.state.checkpointer = saver
    app.state.graph = build_graph(checkpointer=saver)

    # NEW — Phase 4 — create pending_reviews schema if missing
    from src.api.reviews import init_reviews_db
    init_reviews_db()
    logger.info("lifespan: reviews DB ready, graph compiled")

    try:
        yield
    finally:
        await teardown()
```

Do NOT call `init_reviews_db()` at module-import time — that breaks Docker
cold-start ordering (the volume mount happens after import).

### 5.2 New router file: `src/api/routers/reviews.py`

```
GET  /pending_review
     → 200 list[{extraction_id, statement_sha256, created_at,
                 suspect_count, status, reason}]

GET  /review/{extraction_id}
     → 200 {extraction_id, statement_sha256, partial_result, suspects,
            chunk_excerpts}
     → 404 if no such id

POST /review/{extraction_id}
     body: {corrections: [TransactionCorrection], force: bool}
     → 200 ExtractResult (final, resumed)
     → 404 if no such id
     → 409 if status != 'pending'
```

```python
class TransactionCorrection(BaseModel):
    chunk_id: str
    row_index: int                # -1 = insert at end
    action: Literal["edit", "insert", "delete"]
    fields: dict[str, Any] = {}   # date, description, amount, direction, running_balance
```

### 5.3 Endpoint flow — POST /review/{id}

1. Look up `extraction_id` in `reviews.sqlite`; load `thread_id`.
2. Mark `in_review`.
3. Build `Command(resume={"corrections": [...], "force": bool})`.
4. Call `await app.state.graph.ainvoke(Command(resume=...), config={"configurable": {"thread_id": thread_id}, "recursion_limit": 50})`.
5. On graph completion: read final state, return ExtractResult.
6. Mark `resolved`.

### 5.4 await_review node — pause via `interrupt()`

```python
# src/nodes/await_review.py
from langgraph.types import interrupt

def await_review(state: GraphState) -> dict:
    """Pause graph; surface suspects via interrupt(); resume on POST /review.

    NOTE — layer boundary (per critic Finding 8): this node DOES NOT write
    to reviews.sqlite directly.  The API layer (POST /extract handler) is
    responsible for detecting the interrupt via `result["__interrupt__"]`
    on the streaming response and inserting the pending_reviews row.  This
    keeps src/nodes/ free of src/api/ imports.

    Reason is computed inline (resolves critic GAP-D: no `await_reason`
    field in GraphState; await_review re-derives it from the same
    conditions the router used).
    """
    from src.api.pricing import HARD_COST_CAP_USD

    reports = state.get("verifier_reports", [])
    total_suspects = sum(len(r.suspects) for r in reports)
    retry = state.get("retry_count", 0)
    cost_capped = state.get("cumulative_cost_usd", Decimal("0")) >= HARD_COST_CAP_USD

    if cost_capped:
        reason = "cost_ceiling_exceeded"
    elif retry >= 2:
        reason = "retry_exhausted"
    else:  # total_suspects > 3
        reason = "suspects_exceeded"

    payload = {
        "suspects": [s.model_dump() for r in reports for s in r.suspects],
        "partial_periods": [_partial_period_dict(state, chunk_id)
                            for chunk_id in _all_chunk_ids(state)],
        "reason": reason,
    }
    # interrupt() pauses the graph; the value is surfaced in
    # result["__interrupt__"] for the API layer to read.
    response = interrupt(payload)
    # On resume, response is the dict from POST /review/{id}:
    #   {"corrections": [TransactionCorrection, ...], "force": bool}
    return {
        "human_corrections": response.get("corrections", []),
        "force_resume": response.get("force", False),
    }
```

After `await_review`:
- Conditional edge `route_after_review` reads `force_resume`:
  - `force_resume=True` → straight to `finalize` (accept partial extraction as-is).
  - else → `apply_human_corrections` (re-run extraction with the hint).

### 5.5 Decision D4 — rerun extract_transactions with hint (corrected per critic Finding 5)

```python
def apply_human_corrections(state: GraphState) -> list[Send]:
    """Per D4 — re-run extract_transactions for each chunk that has
    human corrections, injecting the correction as a prompt hint.

    CRITICAL (per critic Finding 5): the hint MUST be injected into BOTH
    pdf_text AND ocr_slice, because src/nodes/extract_transactions.py:96
    prefers pdf_text and only falls back to ocr_slice when pdf_text is
    empty.  Injecting only into ocr_slice would silently lose the hint
    on Ixonia and any other PDF-backed chunk.
    """
    sends = []
    grouped = _group_corrections_by_chunk_id(state["human_corrections"])
    for chunk_id, corrections in grouped.items():
        chunk = _find_chunk(state, chunk_id)
        hint_block = _format_correction_hint(corrections)
        annotated_chunk = chunk.model_copy(update={
            "pdf_text":   hint_block + chunk.pdf_text,
            "ocr_slice": (hint_block + chunk.ocr_slice) if chunk.ocr_slice is not None else None,
        })
        sends.append(Send("extract_transactions", annotated_chunk))
    return sends


def _format_correction_hint(corrections: list[TransactionCorrection]) -> str:
    """Build a prompt-prefix block from the human's row-level corrections.
    The extractor MUST treat these as ground truth and incorporate them
    into the final row list."""
    lines = [
        "## Human corrections (treat as ground truth; do not contradict)",
    ]
    for c in corrections:
        if c.action == "edit":
            lines.append(f"- row {c.row_index}: edit fields = {c.fields}")
        elif c.action == "insert":
            lines.append(f"- INSERT at row {c.row_index}: {c.fields}")
        elif c.action == "delete":
            lines.append(f"- DELETE row {c.row_index}")
    lines.append("")
    lines.append("## Statement chunk")
    lines.append("")
    return "\n".join(lines) + "\n"
```

`PeriodChunk` is frozen (`model_config = ConfigDict(strict=True, frozen=True)`)
but `model_copy(update=...)` produces a NEW instance — this is allowed in
Pydantic v2 even on frozen models. The original chunk is unchanged.

After re-extraction, verifier runs again. If still broken AND
`retry_count >= 2`, finalize emits `reconciled=False` with structured
`errors[]` listing the unresolvable rows by chunk_id + row_index.

### 5.6 Cost ceiling enforcement (D5) — superseded

**Superseded by §8.1 and §8.2.** Do NOT define `_HARD_COST_CAP_USD`
locally; import `HARD_COST_CAP_USD` from `src/api/pricing.py`.
There is NO dedicated `track_cost` node and NO `should_run_critic_or_review`
router — cost tracking is inline at the bottom of every `_invoke_llm()`
helper, and the only post-verifier router is `route_after_verifier` (§4.2).
This section is kept as a stub only to preserve the §-numbering used elsewhere.

### 5.7 Subagent + layer-boundary contract (resolves critic Finding 8)

`fastapi-engineer` owns:
- `src/api/reviews.py` (the DB module)
- `src/api/routers/reviews.py` (the new HTTP router)
- The change to `src/api/routers/extract.py` that:
  - detects `result["__interrupt__"]` after `await graph.ainvoke(...)`
  - writes the row to `reviews.sqlite` (insert_pending) using a freshly-
    generated `extraction_id = uuid4()`
  - returns an `ExtractResult` with `pending_review = PendingReview(...)` filled

`langgraph-engineer` owns:
- `src/nodes/await_review.py` — only calls `interrupt()` and returns the
  resume payload as a state delta. Has NO knowledge of `reviews.sqlite`.
- `src/nodes/apply_human_corrections.py` (the Send-fan-out node).
- The new conditional edges in `src/nodes/critic_loop.py` + `src/graph/builder.py`.
- Updating `src/graph/state.py` with the new keys + reducers from §4.3.
- Updating `docs/architecture.md` with the new topology diagram (§4.5).

This split keeps the repo's layer boundary clean: graph nodes never import
from `src/api/`. The DB write is an API-layer concern triggered by reading
the interrupt payload off the graph's response.

Ordering: `langgraph-engineer` finishes first (graph wiring + state schema +
docs/architecture.md), then `fastapi-engineer` integrates the API layer.

### 5.8 Acceptance criteria

- `tests/api/test_reviews.py` (new):
  - `test_list_pending_reviews_empty` — initial state, GET returns `[]`.
  - `test_extract_emits_pending_review_when_cost_capped` — force cost cap
    to $0.01; POST /extract returns `reconciliation.reconciled=False` AND
    creates a `pending_reviews` row.
  - `test_post_review_resumes_graph` — create a paused graph; POST
    `/review/{id}` with a corrections list; assert final ExtractResult
    has reconciled=True (synthetic case) and row in `reviews.sqlite` is
    marked `resolved`.
  - `test_post_review_force_skips_extraction` — `force=True` routes
    directly to finalize without re-running extraction.
- `tests/test_verifier_e2e.py` extended: pause point hit; resume via
  `Command(resume=...)` produces a final ExtractResult.

---

## 6 · Phase 5 — Frontend ReviewModal

### 6.1 New file: `frontend/src/components/ReviewModal.tsx`

Triggered from `App.tsx` when the response includes a non-null
`pending_review` flag (TBD wire this into the response — see §6.2).

UI:

- Modal overlay; cannot be dismissed without action.
- Top: extraction_id, statement_sha256 (first 12 chars), reason.
- For each suspect: row index, code, reason, expected vs actual.
- Each suspect has an inline editor with editable fields.
- Bottom: **[Apply & Re-extract]** button → POST `/review/{id}` with
  corrections array.  **[Force finalize]** button → POST with
  `force=true`.

### 6.2 ExtractResult schema update for frontend

```ts
// frontend/src/types.ts
interface ExtractResult {
  periods: PeriodResult[];
  statement_sha256: string;
  langsmith_run_url: string | null;
  errors: string[];
  pending_review?: {                  // NEW
    extraction_id: string;
    reason: "suspects_exceeded" | "cost_ceiling_exceeded" | "retry_exhausted";
  };
}

interface PeriodResult {
  // ... existing fields
  verifier?: VerifierReport;          // NEW
}
```

### 6.3 New API client function

```ts
// frontend/src/api.ts
export async function submitReview(
  extractionId: string,
  payload: { corrections: TransactionCorrection[]; force: boolean }
): Promise<ExtractResult>;
```

### 6.4 Acceptance criteria

- `pnpm tsc --noEmit && pnpm biome check .` — clean.
- Manual smoke: upload Ixonia → wait for response → if `pending_review`
  is set, ReviewModal opens with suspects rendered.

### 6.5 Subagent

`react-engineer`. Foreground after Phase 4 lands (frontend depends on the
new HTTP contract).

---

## 7 · Database — reviews.sqlite schema (full DDL)

```sql
CREATE TABLE pending_reviews (
    extraction_id     TEXT PRIMARY KEY,
    thread_id         TEXT NOT NULL,
    statement_sha256  TEXT NOT NULL,
    created_at        TEXT NOT NULL,           -- '2026-05-13T18:00:00+00:00'
    status            TEXT NOT NULL
                          CHECK(status IN ('pending', 'in_review', 'resolved', 'aborted')),
    suspect_count     INTEGER NOT NULL DEFAULT 0,
    reason            TEXT,                    -- nullable for pending=0 (no reason)
    review_payload    TEXT NOT NULL            -- JSON: full payload from await_review
);
CREATE INDEX idx_pending_reviews_status  ON pending_reviews(status);
CREATE INDEX idx_pending_reviews_created ON pending_reviews(created_at);
```

Lifecycle:
- `pending`   — inserted by `src/api/routers/extract.py` when it detects
                 `result["__interrupt__"]` after the graph pauses (per §5.7
                 layer-boundary rule; `await_review` node does NOT write
                 to the DB)
- `in_review` — set by GET /review/{id} (optimistic concurrency)
- `resolved` — set by POST /review/{id} after graph resumes successfully
- `aborted`   — set if the user cancels or the request times out

A nightly cron (out of scope for this PRD) can purge `resolved` rows older
than 30 days.

---

## 8 · Cost ceiling enforcement (D5 — concrete spec)

### 8.1 Tracking cost in-graph

LangChain's `usage_metadata` returns input/output token counts per call.
We compute cost server-side using a frozen pricing table. Both the pricing
table AND the hard cap live in `src/api/pricing.py` (single source for all
cost-control constants, resolves critic GAP-C):

```python
# src/api/pricing.py — frozen May-2026 prices + hard cap
import os
from decimal import Decimal

PRICING_USD_PER_M_TOKENS = {
    "claude-haiku-4-5":    {"input": Decimal("0.25"), "output": Decimal("1.25")},
    "claude-sonnet-4-6":   {"input": Decimal("3.00"), "output": Decimal("15.00")},
}

# D5 — abort the request when cumulative LLM spend reaches this dollar value.
# Overridable via env for tests / pathological statements.
HARD_COST_CAP_USD: Decimal = Decimal(os.environ.get("BSA_COST_CAP_USD", "5.00"))


def call_cost(model: str, usage: dict) -> Decimal:
    p = PRICING_USD_PER_M_TOKENS[model]
    in_tok = Decimal(usage.get("input_tokens", 0))
    out_tok = Decimal(usage.get("output_tokens", 0))
    return ((in_tok * p["input"]) + (out_tok * p["output"])) / Decimal("1000000")
```

### 8.2 Wire into every LLM-using node (resolves critic GAP-E)

There is NO dedicated `track_cost` node. Each LLM-using node updates
`cumulative_cost_usd` **inline** right after its `llm.invoke(...)` call.
Pattern:

```python
# At the bottom of _invoke_llm() (or equivalent) in:
#   src/nodes/classify_layout.py
#   src/nodes/extract_account.py
#   src/nodes/extract_summary.py
#   src/nodes/extract_transactions.py
#   src/nodes/critic_loop.py
from src.api.pricing import call_cost
from decimal import Decimal

raw_result = llm_with_output.invoke([system, user])
# ... extract result.usage_metadata via langchain's response_metadata ...
usage = getattr(raw_result, "usage_metadata", None) or {}
model_name = getattr(llm_with_output, "model_name", "claude-sonnet-4-6")
this_call_cost: Decimal = call_cost(model_name, usage)

# Return the cost increment alongside the existing payload; the
# `operator.add` reducer on cumulative_cost_usd sums it into state.
return {
    # ... existing fields like "accounts": [account] ...
    "cumulative_cost_usd": this_call_cost,
}
```

`operator.add` on `Decimal` is associative + commutative → safe under
parallel Send fan-out. Initial state must seed `Decimal("0")` at the
sites listed in §4.4.

### 8.3 Conditional edge

`route_after_verifier` (defined in §4.2) checks
`state.get("cumulative_cost_usd", Decimal("0")) >= HARD_COST_CAP_USD`
BEFORE routing to critic. If exceeded, forces `await_review`; the
`await_review` node then derives `reason="cost_ceiling_exceeded"` (§5.4).

---

## 9 · Acceptance — end-to-end

After all 5 phases:

1. `uv run ruff check . && uv run ruff format --check . && uv run mypy src
   && uv run pytest -q` — all green, ≥ 135 tests pass.
2. `python3 tests/fixtures/run_all.py` — 4/5 fixtures fully match, all 4 reconciled.
3. `curl -sS -X POST -F file=@/Users/izual/Downloads/Binder2_Redacted.pdf
   -F ocr_text=@Task/ixonia_binder2_ocr.txt http://localhost:8000/extract`
   - returns ExtractResult with 10 periods
   - 9/10 reconciled (≥ baseline)
   - period_08 either reconciles after verifier-driven retry, or emits a
     `pending_review` with the specific broken row identified
   - cost in LangSmith ≤ $1.30 per run (-50 % vs baseline)
4. `curl http://localhost:8000/pending_review` — lists the paused
   period_08 review (if it's still paused).
5. Manual frontend smoke: upload a broken statement, see ReviewModal,
   submit corrections, see final reconciled=True result.

---

## 10 · Out of scope (will not implement in this PRD)

- Multi-reviewer workflow / assignment / audit log.
- Streaming `/extract` responses (current 5:42 wall-clock makes streaming
  worthwhile but it's a separate UX concern).
- Caching extracted results by `statement_sha256` (an explicit cache layer).
- Batch API mode (process multiple statements in one POST).
- OCR — still consumed as input.

---

## 11 · Open execution risks

| Risk | Mitigation |
|---|---|
| Haiku 4.5 mis-extracts summary on noisy OCR (stmt_05-style) | Verifier C6 catches summary delta; route to critic with Sonnet retry. |
| `interrupt()` semantics differ in async vs sync LangGraph | Verified via context7 docs — async pattern is `await graph.ainvoke(Command(resume=...), config)`. Tested in Phase 4 acceptance criteria. |
| `cumulative_cost_usd` reducer races on parallel Send fan-out | `operator.add` on Decimal is associative — correct. Verify via Phase 4 cost-cap test. |
| Reviews DB grows unbounded | Out-of-PRD cron; add `pragma auto_vacuum`. |
| Human correction format too rigid (only edit/insert/delete on rows) | Reviewer can use `force=true` to bypass extraction and accept the partial result as-is. |

---

## 12 · Done definition

This PRD is "done" when:

- ✅ Phase 1 commit: `feat(cost): switch account+summary to Haiku 4.5, strip chunk_id from tx schema`
- ✅ Phase 2 commit: `feat(verifier): C1-C6 deterministic per-row checks`
- ✅ Phase 3 commit: `feat(graph): verifier ↔ critic ↔ await_review routing`
- ✅ Phase 4 commit: `feat(api): pending_review endpoints + HITL resume via LangGraph interrupt()`
- ✅ Phase 5 commit: `feat(frontend): ReviewModal + correction submission`
- ✅ Critic-approval JSON on each phase before commit
- ✅ End-to-end acceptance §9 passes on the deployed stack

The next session should start by reading this PRD, running
`gitnexus context bank-statement-analizer` to refresh on current symbols,
then jumping straight to **Phase 1** (lowest risk, highest immediate $ value).

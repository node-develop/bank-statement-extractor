# Plan — cost reduction + verifier agent + human-in-the-loop

**Status:** DRAFT for review (2026-05-13).
**Audience:** owner (dev@artka.dev).
**Goal:** cut per-extraction cost ~2-3× and eliminate guessing by adding a
deterministic verifier + escalation path to a human reviewer.

---

## 1 · Cost baseline (measured, real LLM)

From LangSmith trace `019e1f7f` — full Ixonia `Binder2_Redacted.pdf`,
10 periods, 869 transactions:

| Metric | Value |
|---|---:|
| LLM calls | 42 |
| Input tokens | 277 977 |
| Output tokens | 121 286 |
| **Total cost** | **$2.55** |
| Wall-clock | 5:42 |

Per node (estimated from token totals; Sonnet 4.6 = $3/M in + $15/M out;
Haiku 4.5 = $0.25/M in + $1.25/M out):

| Node | Model | Calls/run | ~Input/call | ~Output/call | Cost/run |
|---|---|---:|---:|---:|---:|
| `classify_layout` | Haiku 4.5 | 10 | 2 000 | 30 | $0.005 |
| `extract_account` | Sonnet 4.6 | 10 | 6 000 | 100 | $0.20 |
| `extract_summary` | Sonnet 4.6 | 10 | 6 000 | 250 | $0.22 |
| `extract_transactions` | Sonnet 4.6 | 10 | 14 000 | 12 000 | **$2.22** |
| `critic` | Haiku 4.5 | 2 | 1 500 | 80 | $0.001 |

**`extract_transactions` is 87% of total cost** because output is huge
(192 tx × ~150 tokens = ~29k output tokens for the worst period).

For a 1-page statement (Chase test): ~$0.05.

---

## 2 · Cost-reduction proposal

### 2.1 Model routing

| Node | Current | Proposed | Why |
|---|---|---|---|
| `classify_layout` | Haiku 4.5 | **keep Haiku** | single-label routing |
| `extract_account` | Sonnet 4.6 | **Haiku 4.5** | header text only, ~6 fields |
| `extract_summary` | Sonnet 4.6 | **Haiku 4.5** | 6 known fields, anchor-driven |
| `extract_transactions` | Sonnet 4.6 | **keep Sonnet** | precision-critical, long output |
| `critic` | Haiku 4.5 | **keep Haiku** | judgment, not extraction |
| `verifier` (new) | — | **Haiku 4.5** | deterministic checks + small judgment |

Projected per-Ixonia cost: **$2.55 → $1.30** (-49%).

Risk: Haiku may mis-extract account_last4 / period dates. Mitigation
already exists for account_last4 (deterministic `split_periods` regex
overrides LLM). For period dates we keep verifier sanity check.

### 2.2 Prompt-cache discipline

We already split System (cached, ephemeral) + Human (dynamic). With 10
parallel chunks per Ixonia, the cached system prefix is reused 9/10 calls
per extractor → ~15-20% input-cost savings on the cached portion.

LangSmith doesn't show cached-token breakdown in our current run names.
**Action:** add `usage_metadata` logging so we can verify cache hits in
LangSmith and tune.

### 2.3 Output-token reduction

For `extract_transactions`, each row currently outputs:
```json
{"chunk_id": "...", "date": "...", "description": "...",
 "amount": "...", "direction": "credit|debit", "running_balance": "..."}
```

`chunk_id` is the same on every row (~30 tokens × 192 = 5 760 wasted
tokens for one period). **Action:** strip `chunk_id` from per-row schema
in the LLM-facing model, inject it server-side after extraction.

Projected output savings: ~10% per heavy chunk.

### 2.4 Total cost target

| Workload | Now | After §2.1+§2.3 | Δ |
|---|---:|---:|---:|
| 1-page personal checking | $0.05 | $0.025 | -50% |
| Ixonia 10-period (869 tx) | $2.55 | $1.10 | -57% |
| Single Chase business (18 tx) | $0.05 | $0.025 | -50% |

---

## 3 · Verifier agent + human-in-the-loop

### 3.1 What the verifier guarantees

The verifier runs AFTER `extract_transactions` and BEFORE `reconcile`.
It enforces:

| Check | Hard fail / soft fail | Action on fail |
|---|---|---|
| **C1 running-balance consistency** — `prev_balance + signed_amount == this_balance` (±$0.01) per row | hard | flag row as suspect; expected_balance vs actual_balance in note |
| **C2 date monotonicity** — `tx[i].date >= tx[i-1].date` | hard | flag both rows |
| **C3 no duplicate (date, amount, direction) triplets unless description differs** | soft | flag for review |
| **C4 description not empty / not "BEGINNING/ENDING BALANCE"** | hard | reject row |
| **C5 amount = 0** | hard | reject row |
| **C6 pre-reconcile delta** — sum credits/debits vs summary; if off, identify which row's running_balance breaks the chain | hard | flag the breaking row + a confidence score |

Output: `VerifierReport(chunk_id, suspects=[Suspect(row_index, reason, expected, actual)], gaps=[Gap(date_range, missing_amount)], confidence: float)`.

### 3.2 Routing decision tree

```
verifier emits N suspects + M gaps:
├─ N==0 and M==0  → proceed to reconcile (happy path)
├─ N+M ≤ 3        → critic loop with verifier_hint  (existing retry path; bounded)
└─ N+M > 3 OR after 2 retries still failing
                  → state["pending_review"] = True; finalize emits
                    ExtractResult with reconciled=False AND review_token
                    AND list of suspects + chunk_text excerpts
                    → graph pauses via LangGraph interrupt()
```

### 3.3 Human-in-the-loop API

Two new endpoints in `src/api/routers/extract.py`:

```
GET  /pending_review            → list of {extraction_id, statement_hash,
                                  created_at, n_suspects, status}
GET  /review/{extraction_id}    → ReviewPayload {suspects, chunk_excerpts,
                                  partial_extract_result}
POST /review/{extraction_id}    → {corrections: [TransactionCorrection]}
                                  → resumes the paused LangGraph
```

`TransactionCorrection` = `{row_index, action: "edit|insert|delete",
fields: {date, description, amount, direction, running_balance}}`.

### 3.4 LangGraph wiring

Add **two new nodes** + **two new edges**:

```
... → extract_transactions → verifier ──┬─ all_good → reconcile → ...
                                        ├─ retryable → critic (existing)
                                        └─ needs_human → await_review (NEW)
                                                            │
                                                            interrupt()
                                                            │
                                                  POST /review/{id}
                                                            │
                                                            ▼
                                                   merge_corrections → reconcile
```

`interrupt()` is the documented LangGraph pause primitive
(docs.langchain.com/oss/python/langgraph/human-in-the-loop). The state
checkpointer (SQLite) holds the paused state; the HTTP POST resumes the
graph with the human-provided corrections.

### 3.5 Why this kills guessing

Today, on a non-reconciling period the critic just records a hint into
`errors[]` and we emit `reconciled=False`. The user sees that and has
no way to drill down or fix specific rows.

With the verifier:
- **Every emitted transaction passes C1-C6** or is explicitly listed as a
  suspect — no silent guess.
- **`reconciled=False` carries a structured cause** (which rows are
  broken, what running-balance chain expects) rather than a vague delta.
- **Human review is one API call away** when the LLM can't self-correct.

This satisfies CLAUDE.md rule 12 ("fail loud, surface uncertainty") at a
row level, not just at the period level.

---

## 4 · Estimated effort

| Phase | Scope | Files | LoC | Test budget |
|---|---|---|---:|---|
| **P1** Model routing + chunk_id stripping | swap models in 4 extractors; refactor `_TransactionList` to omit chunk_id; verify cost via LangSmith | 4 nodes + 1 prompt | ~50 | re-run Ixonia, assert 9/10 reconciled stays |
| **P2** Verifier node + checks C1-C6 | new `src/nodes/verifier.py` + tests; new VerifierReport model | 2 + tests | ~250 | unit tests on each of C1-C6; integration on stmt_01 |
| **P3** Wire verifier into graph; emit suspects to errors[] | `builder.py` + `finalize.py` + `state.py` | 3 | ~80 | new E2E test: synthetic broken period → suspects emitted |
| **P4** Human-in-the-loop API | new `/pending_review`, `/review/{id}` routes; LangGraph `interrupt()`; sqlite-backed paused state | router + builder | ~200 | integration: post correction, assert state resumes |
| **P5** Frontend banner + correction modal | `frontend/src/components/ReviewModal.tsx` + API client | 1 + types | ~250 | manual smoke |

Total: ~830 LoC, ~3 sessions worth of work at 30k token budget each.

**Order of execution (recommended):**
1. **P1 first** — cheap, immediate cost win, low risk.
2. **P2** — verifier alone is useful even without HITL; surfaces row-level
   issues in `errors[]`.
3. **P3** — wire it.
4. **P4 + P5 together** — full HITL flow.

---

## 5 · Decisions (locked 2026-05-13)

- **D1 — model routing**: Haiku 4.5 OK for `extract_account` and
  `extract_summary`. Deterministic regex override on `account_last4`
  (already in M2) plus the new verifier (C6 pre-reconcile delta)
  catches any drift.
- **D2 — review granularity**: **per-statement**. The reviewer sees the
  whole ExtractResult in one screen, with suspect rows highlighted
  across all periods. Reduces context switching; one approval finishes
  the run.
- **D3 — HITL persistence**: new dedicated table `pending_reviews` in
  a SEPARATE sqlite file `./reviews.sqlite` (NOT inside `graph.sqlite`
  which is the LangGraph checkpointer). The table maps
  `extraction_id ↔ thread_id` plus stores `created_at`, `status`,
  `statement_sha256`, `suspect_count`. The LangGraph checkpointer
  remains its own immutable store; the reviews table is the
  application-level index.
- **D4 — correction semantics**: on POST `/review/{id}`, re-run the
  full `extract_transactions` for the affected chunk(s) with the
  human's correction injected as a hint into the prompt. Doubles LLM
  cost on that chunk only, but keeps the model in charge of producing
  the final validated row set (auditable single source of truth).
- **D5 — cost ceiling**: hard cap **$5** per request. If cumulative
  per-request LLM spend (tracked via LangSmith run metadata) exceeds
  the cap, abort further LLM calls, emit
  `pending_review=True, reason="cost_ceiling_exceeded"`, and surface
  whatever was extracted so far. Reviewer can resume by hitting POST
  `/review/{id}` with `force=True`.

---

## 6 · Non-goals (this plan does NOT)

- Replace Sonnet 4.6 for transaction extraction (precision matters most
  there; cost is already concentrated on that one node).
- Add OCR — we still consume OCR as input.
- Build a full review-UI workflow management (assignment to specific
  reviewers, audit log, etc.). Single reviewer assumed for now.
- Cache full extractions across requests (sha256-based cache is a
  separate concern; the LangGraph checkpointer is run-scoped, not
  content-scoped).

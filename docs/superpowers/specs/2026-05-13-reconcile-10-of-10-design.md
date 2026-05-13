# Reconcile 10/10 on Binder2 — Sprint Design

Status: approved 2026-05-13
Branch: `frontend-redesign`
Baseline: commit `3ba46d5` ("feat: Azure DI OCR + HITL streaming + frontend UX polish")

## Goal

Land the next sprint so that `Task/Binder2_Redacted.pdf` reconciles 10 / 10
periods against `docs/ixonia-etalon.md` (currently 0 / 10 reconcile, 7 / 10
summaries exact-match).

## Root cause

Reading `src/nodes/split_periods.py` lines 277-301 (`_find_page_range`) and
`src/nodes/extract_transactions.py` lines 118-127 against the Ixonia OCR:

| File / line | Bug | Effect |
|---|---|---|
| `split_periods.py` L277-301 `_find_page_range` | `last_page` is computed from the line `Ending Balance as of MM/DD/YYYY`, but in the Ixonia layout that line lives in the **summary block at the top of the period**, not on the last transaction page. | `pdf_text = "\n".join(raw.pages[first_page-1 : last_page])` for each chunk covers ~1 page out of ~9. |
| `extract_transactions.py` L120 | `chunk.pdf_text if chunk.pdf_text else (chunk.ocr_slice or "")` falls back via truthy. A truncated-but-non-empty `pdf_text` is truthy → fallback never fires. | LLM sees only the summary, returns ~5-20 transactions vs. the ~200 actual; counts and totals miss; verifier flags 8-17 suspects; HITL pauses the run. |
| Commit `3ba46d5` body | Calls this out explicitly: "transactions truncate on chunks whose slice does not cover all transaction pages". | Confirmed. |

`ocr_slice` (split_periods.py L182-186) already slices by `lines[beg_idx :
next_beg_idx]` and covers the full period. The fix is to make `pdf_text` use
the same **next-anchor-minus-1** logic and then have `extract_transactions`
prefer `pdf_text` deterministically.

## Scope

Three tasks, in order.

### Task A — `split_periods` full-page slicing

Owner agent: `langgraph-engineer`.

Changes to `src/nodes/split_periods.py`:

- Refactor `_find_page_range` (or inline its logic in the chunk-build loop):
  - `first_page` = first page in `raw.pages` whose text contains the
    period-specific `Beginning Balance as of MM/DD/YYYY` anchor.
    Same as today.
  - `last_page` = `next_period_first_page - 1`, where `next_period_first_page`
    is the `first_page` resolved for chunk `k+1`. For the last chunk
    (`k == n_chunks - 1`), `last_page = len(raw.pages)`.
  - Defensive cap: `last_page = max(first_page, min(last_page, len(raw.pages)))`.
  - When `first_page` is not resolvable (anchor not found in any page),
    fall back to `previous_chunk.last_page + 1` for the start; if the
    previous chunk doesn't exist, start at page 1.
- Keep the existing whole-doc fallback (`n_chunks == 0`) untouched.
- Update the surrounding code so `pdf_text = "\n".join(raw.pages[first_page-1 :
  last_page])` continues to work.

Tests — extend `tests/nodes/test_split_periods.py`:

1. `len(chunks) == 10` on Binder2 fixture (already asserted).
2. For every chunk: `first_page <= last_page`.
3. Monotonicity: `chunks[i].page_range[0] <= chunks[i+1].page_range[0]`
   for all `i < 9`.
4. `len(chunks[0].pdf_text) > 1500` — Apr 2025 has 192 transactions; the
   summary alone is ~600 chars, transactions ≥ 1000.
5. `sum(last - first + 1 for chunk in chunks) >= len(raw.pages) - 2` — every
   page should be claimed by at least one period (small ±2 slack for the
   masthead / footer pages outside any "Beginning Balance" anchor).

### Task B — `extract_transactions` input switching

Owner agent: `langgraph-engineer`.

Changes to `src/nodes/extract_transactions.py` lines 118-127:

- Replace truthy-fallback with an explicit branch on
  `chunk.pdf_text.strip()`:
  - If non-empty → use `pdf_text`; log
    `extract_transactions: <chunk_id> using pdf_text (N chars)`.
  - Else → use `chunk.ocr_slice or ""`; log
    `extract_transactions: <chunk_id> using ocr_slice fallback (N chars)`.
- No prompt edits in this sprint — the EXHAUSTIVENESS REQUIREMENT block is
  already in `src/prompts/extract_transactions.md` from commit `3ba46d5`.

Tests — extend `tests/nodes/test_extract_transactions.py`:

1. Both fields populated → LLM invocation receives the `pdf_text` content,
   `ocr_slice` is ignored.
2. `pdf_text=""`, `ocr_slice="<ocr text>"` → LLM receives `ocr_slice`.

### Task C — Smoke + iterate

Owner agent: `evaluator`.

1. Local smoke run:
   `uv run python -m src.evals.run --statement Task/Binder2_Redacted.pdf`
   with `ANTHROPIC_API_KEY`, `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY` set.
2. Read the latest report in `src/evals/reports/` and compare each of the
   10 periods to the etalon in `docs/ixonia-etalon.md`:
   `account_last4`, `deposits_count`, `withdrawals_count`,
   `deposits_total`, `withdrawals_total`, `beginning_balance`,
   `ending_balance`, `reconciliation.reconciled`.
3. Iteration budget: ≤ 2 iterations. After Task A + Task B, if reconcile
   is < 10 / 10, identify which of the three documented residual gaps
   apply (see "Out of scope") and decide:
   - Iterate within scope on prompt formatting or page boundary tweaks.
   - Or accept the partial result and emit a per-period
     `reconciled: false` with explicit `delta` (rule 12).

## Acceptance criteria

- `uv run pytest -q` — 147 / 147 prior tests green, plus the new
  `split_periods` and `extract_transactions` tests green.
- `uv run ruff check . && uv run ruff format --check . && uv run mypy src`
  — clean.
- `uv run python -m src.evals.run --statement Task/Binder2_Redacted.pdf`
  produces a report where:
  - period_01 (Apr 2025, account 1664) exact-matches the etalon:
    81 deposits / $1,214,254.05, 111 withdrawals / $1,302,201.16,
    beginning $597,068.70, ending $509,121.59, reconciled true.
  - ≥ 7 / 10 periods reconcile (current baseline: 0 / 10). Target: 10 / 10.
- LangSmith trace: every `extract_transactions` node receives a
  `chunk_text` block of ≥ 1500 characters.
- End-to-end cost per statement ≤ $1.50 (current baseline: $0.70).

## Out of scope

These are documented gaps in commit `3ba46d5` body and will be addressed in
separate sprints:

- `extract_summary` column-disambiguation on May 2025 and Nov 2024
  (currently picks the wrong column for `withdrawals_total`).
- `split_periods` intra-month account split (Sep 2024 has both account
  4664 and 4623 — currently emits one chunk per month).
- Holdout / unseen-bank evaluation.
- Frontend changes.

If 9 / 10 reconcile is reached after Task A + Task B and the one
non-reconciling period falls into one of the gaps above, the sprint ships
as-is with explicit `reconciled: false` + `delta` per rule 12.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| OCR page-feed (`\f`) is unreliable on Tesseract output → `raw.pages` boundaries don't line up with period boundaries → `pdf_text` slice includes the previous period's tail. | Defensive cap `last_page = max(first_page, min(last_page, len(raw.pages)))` plus a `notes[]` warning when `last_page - first_page > 12`. Test asserts monotonic non-overlapping page ranges. |
| Sonnet 4.6 still misses transactions on dense periods (`period_02` May 2025: 237 tx) even with full-page `pdf_text`. | Rely on the EXHAUSTIVENESS REQUIREMENT prompt block already in place (commit `3ba46d5`). If a 2nd iteration is needed, the safest knob is adding `--- page N ---` markers inside `pdf_text` between joined pages so the LLM can verify it scanned every page. |
| Cost overrun on iteration. | `BSA_COST_CAP_USD` already enforced server-side. `cumulative_cost_usd` reducer is associative; await_review will pause if breached. |

## Agent invocation order

1. `langgraph-engineer` — Task A.
2. `langgraph-engineer` — Task B.
3. `evaluator` — Task C.
4. `critic` — final 12-rules review against the diff before any commit.

## Out-of-band references

- Etalon: `docs/ixonia-etalon.md`.
- Architecture invariants: `docs/architecture.md` § "Domain invariants",
  § "Ixonia regression fixture".
- Last commit body: `3ba46d5` ("Known gaps for the next sprint" block).

# Architecture

## Goal in one sentence

`extract(pdf_path, txt_path) → dict` returns `{account, summary, transactions}`
for any bank statement, reconciles totals, and refuses to guess.

## Graph topology

A single PDF may carry multiple periods (the Ixonia sample has 10). The graph
splits the raw text into one `PeriodChunk` per period, then fans out the three
extractors per chunk via the LangGraph 1.0 `Send` API. Reducers accumulate the
per-period results back into list-shaped state.

```
ingest ──► split_periods ──► (Send per chunk)
                                ├─► classify_layout (Haiku 4.5)
                                ├─► extract_account
                                ├─► extract_summary
                                └─► extract_transactions
                                          │
                                          ▼
                                    merge_state
                                          │
                                          ▼
                                    reconcile (pure Python, per period)
                                    │           │
                                    │           ▼
                                    │      critic_loop (≤ N=2 retries)
                                    │           │
                                    ▼           ▼
                                  finalize ◄────┘
```

- `ingest` — load PDF (pdfplumber primary, pypdf fallback). If `txt_path` is
  given, load OCR text. **Source-selection policy is here, not silently inside
  extractors**: PDF-extracted text is primary; OCR text is only consulted for
  pages where pdfplumber returned empty/garbage. Any disagreement between
  sources on a non-empty page is appended to `errors[]` (rule 7).
- `split_periods` — **deterministic Python**, no LLM. Regex anchors:
  `Statement Period`, `Beginning Balance`, `Ending Balance`, plus account-
  number changes within the same calendar month (Ixonia Sep 2024 has both
  4664 and 4623; May 2025 / Nov 2024 carry the `*` transition rows).
  Emits `list[PeriodChunk]`. **No LLM fallback on regex miss** (rule 5) —
  on miss, write a specific error to `errors[]` and let `finalize` surface
  `reconciled: false`.
- `classify_layout` — Haiku 4.5 per chunk; picks
  `{ixonia_business_basic, generic_us_bank, unknown}`. Drives prompt
  selection only; never branches Python.
- `extract_account` / `extract_summary` / `extract_transactions` — Sonnet 4.6
  per chunk, `with_structured_output(PydanticModel)`. Fan-out via `Send` so
  all three run in parallel for each period; periods themselves are independent
  branches. Shared system prompt uses Anthropic prompt caching
  (`cache_control: {"type": "ephemeral"}`) so the 10-period fan-out reuses
  the cached prefix.
- `merge_state` — deterministic merge of per-period results into list state.
- `reconcile` — pure Python, `Decimal`. For each period: computes
  `Σdeposit_amounts`, `Σwithdrawal_amounts`, verifies counts against
  `summary.deposits_count` / `withdrawals_count`, checks
  `beginning + Σdeposits − Σwithdrawals == ending` ± ε ($0.01).
- `critic_loop` — only on mismatch. Haiku 4.5 inspects the diff, proposes
  which extractor of which period to re-run with what hint; max 2 iterations;
  if still unreconciled → `finalize` with `reconciled: false` and explicit
  `delta` (rule 12).
- `finalize` — assemble final dict (list of periods), attach LangSmith
  run URL.

## State shape

State is list-shaped to carry multi-period output. Each extractor branch
emits one entry per period; reducers append to the lists. The terminal
output is `ExtractResult.periods: list[PeriodResult]`.

```python
class GraphState(TypedDict):
    pdf_path: str
    txt_path: str | None
    raw: RawStatement                                  # pages + ocr_text + sha256
    period_chunks: list[PeriodChunk]                   # produced by split_periods
    layouts: Annotated[list[LayoutLabel], operator.add]
    accounts: Annotated[list[Account], operator.add]
    summaries: Annotated[list[Summary], operator.add]
    transactions: Annotated[list[Transaction], operator.add]
    reconciliations: Annotated[list[Reconciliation], operator.add]
    retry_count: int
    errors: Annotated[list[str], operator.add]
```

Each `PeriodChunk` carries `{chunk_id, pages, ocr_slice, account_hint_last4}`
so reducers can stitch results back together by `chunk_id`. The
`Reconciliation` model carries `chunk_id`, `reconciled`, `delta`, `notes`.

## Checkpointer

`langgraph.checkpoint.sqlite.SqliteSaver` by default (file `./graph.sqlite`).
Set `LANGGRAPH_CHECKPOINTER=postgres` + `DATABASE_URL=postgresql://...` to
switch to `PostgresSaver` in production (Dokploy injects this).

## LangSmith

- Project: `bank-statement-analizer-${ENV}` (`dev` / `prod`).
- Tags: `["extract", "<bank_slug>"]`.
- Metadata: `{statement_sha256, statement_pages, total_tx_expected}`.
- Datasets: `ixonia-binder2` (10 periods, etalon from `Task/task.md`),
  `holdout-banks` (added as we accumulate unseen statements).

## Domain invariants (carved by reading the Ixonia OCR)

These rules sit in the extractor prompts and in `reconcile`'s validation;
they are not bank-specific, they are **bank-statement-extraction** primitives.

1. **Column position is lost in OCR.** Do **not** rely on whether an amount
   appears in a "Deposits" or "Withdrawals" column — Azure DI flattens
   columns into a single text stream. Assign the amount by sign of the
   running-balance delta:
   ```
   sign = balance_after_row - balance_before_row
   if sign > 0: row is a deposit (amount = +sign)
   if sign < 0: row is a withdrawal (amount = -sign)
   ```
   The first row of a period uses `summary.beginning_balance` as
   `balance_before_row`. This is the **only** column-disambiguation rule
   the extractor is allowed to use.
2. **Skip pseudo-rows from counts.** `BEGINNING BALANCE` and `ENDING
   BALANCE` lines have no amount column and must not contribute to
   `deposits_count` / `withdrawals_count` / `*_total`.
3. **Stitch multi-line descriptions.** Where an OCR row carries text but
   no amount (e.g. trailing `LLC`, `CORP`, a long ACH continuation), it
   belongs to the previous transaction's `description`. Join with a single
   space, trim trailing whitespace, preserve internal whitespace verbatim.
4. **Currency normalization on parse only.** Strip `$`, thousands separators,
   and the documented OCR oddity `$509, 121.59` (stray space at OCR line
   1134) — but never mutate the value, only the textual form. Output is
   `Decimal` strings.

## Ixonia regression fixture (for `split_periods` tests)

The deterministic period-splitter must produce exactly 10 chunks on
`Task/ixonia_binder2_ocr.txt`, with the `Beginning Balance as of …`
header appearing at these OCR line numbers (1-based):

| # | Line | Period   | Account hint        |
|---|------|----------|---------------------|
| 1 | 38   | Apr 2025 | `1664` (raw)        |
| 2 | 1133 | May 2025 | `XXXXXX4664` (masked, etalon shows `1664*` — discrepancy, see `docs/ixonia-etalon.md`) |
| 3 | 2379 | Jun 2024 | `1664` (raw)        |
| 4 | 3399 | Jul 2024 | `4664` (raw)        |
| 5 | 4410 | Aug 2024 | `4664` (raw)        |
| 6 | 5297 | Sep 2024 | `4664` (raw)        |
| 7 | 6280 | Sep 2024 | `4623` (raw, second account in same month) |
| 8 | 6620 | Oct 2024 | `4664` (raw)        |
| 9 | 7591 | Nov 2024 | `XXXXXX4664` (masked, etalon `4664*`) |
| 10| 8632 | Dec 2024 | `4664` (raw)        |

`tests/nodes/test_split_periods.py` must assert: (a) length 10, (b) each
chunk's header line equals the table above, (c) `chunk.account_hint_last4`
extracted from `^Account Number:\s*(?:XXXXXX)?(\d{4})$`, (d)
`chunk.is_account_transition == ("XXXXXX" in raw_account_line)`.

## Generalization strategy (rule 4, rule 7)

Adding a new bank is **prompt-only**:
1. Drop one redacted sample under `evals/fixtures/<bank>/`.
2. Add a prompt exemplar in `src/prompts/extract_transactions.md` under a
   new `### <Bank>` section. ≤ 1 example.
3. Add the bank label to `classify_layout`'s allow-list.
4. Run `uv run python -m src.evals.run --statement <path>`.

If reconciliation still fails after 2 critic retries, the response carries
`reconciled: false` — we never invent numbers.

## Error model

| Condition | Response |
|---|---|
| PDF unreadable | HTTP 422, `{error: "pdf_unreadable", detail}` |
| Layout classifier returns `unknown` | Continue with `generic_us_bank` prompts, tag run `unknown_layout` in LangSmith |
| Reconciliation fails after N retries | HTTP 200, body includes `reconciliation.reconciled = false` and `delta` |
| OCR confidence < threshold (when computable) | Warning in `notes[]`, never silent |
| Anthropic 5xx | Retry with exponential backoff (LangChain default), surface after 3 attempts |

# Architecture

## Goal in one sentence

`extract(pdf_path, txt_path) → dict` returns `{account, summary, transactions}`
for any bank statement, reconciles totals, and refuses to guess.

## Graph topology

```
ingest ──► classify_layout ──► (parallel)
                                ├─► extract_account
                                ├─► extract_summary
                                └─► extract_transactions
                                          │
                                          ▼
                                    merge_state
                                          │
                                          ▼
                                    reconcile (pure Python)
                                    │           │
                                    │           ▼
                                    │      critic_loop (≤ N=2 retries)
                                    │           │
                                    ▼           ▼
                                  finalize ◄────┘
```

- `ingest` — load PDF (pdfplumber primary, pypdf fallback), load OCR text if
  given; emit `RawStatement{pages, ocr_text, hash}` into state.
- `classify_layout` — Haiku 4.5; picks one of: `{ixonia_business_basic,
  generic_us_bank, unknown}`. Drives prompt selection downstream. No code
  branches on bank — only the prompt template changes.
- `extract_account` — Sonnet 4.6; structured output (pydantic) for
  `Account{bank, account_last4, period{start,end}}`.
- `extract_summary` — Sonnet 4.6; structured output for `Summary` fields.
- `extract_transactions` — Sonnet 4.6; chunked by period when statement spans
  multiple months; structured output for `list[Transaction]`.
- `merge_state` — deterministic merge into the graph state.
- `reconcile` — pure Python, `Decimal`. Computes
  `Σdeposit_amounts`, `Σwithdrawal_amounts`, compares with summary, sets
  `reconciled: bool`, `delta: Decimal`, `notes: list[str]`.
- `critic_loop` — only on mismatch. Haiku 4.5 inspects the diff, proposes
  which extractor to re-run with what hint; max 2 iterations; if still
  unreconciled → `finalize` with `reconciled: false` and explicit `delta`.
- `finalize` — assemble final dict, attach LangSmith run URL.

## State shape

```python
class GraphState(TypedDict):
    pdf_path: str
    txt_path: str | None
    raw: RawStatement
    layout: Literal["ixonia_business_basic", "generic_us_bank", "unknown"]
    account: Account | None
    summary: Summary | None
    transactions: Annotated[list[Transaction], extend]
    reconciliation: Reconciliation | None
    retry_count: int
    errors: Annotated[list[str], append]
```

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

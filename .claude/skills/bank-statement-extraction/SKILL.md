---
name: bank-statement-extraction
description: Domain primer for bank-statement extraction — period semantics, deposit vs withdrawal conventions, balance algebra, statement-cycle anomalies. Use whenever working on extraction prompts, reconciliation, or the graph nodes that touch summary or transactions. Do NOT use for generic OCR work.
---

# Bank-statement extraction — domain primer

## Vocabulary

- **Statement period**: a single billing cycle, usually one calendar month
  but can be off-cycle (e.g. account opened mid-month). Defined by
  `period.start` and `period.end` inclusive.
- **Beginning balance**: balance carried in from the previous period.
- **Ending balance**: balance at end of period. Must equal
  `beginning + Σdeposits − Σwithdrawals`.
- **Deposit / credit**: positive money movement INTO the account. In the
  Ixonia layout, column "Deposits".
- **Withdrawal / debit**: positive money movement OUT of the account. In
  the Ixonia layout, column "Withdrawals".
- **Service charges**: typically a withdrawal, but reported on its own line
  in the summary. Counts in `withdrawals_total` AND `withdrawals_count`.
- **`account_last4`**: last 4 digits of the displayed account number. When
  the layout shows a longer number, take only the trailing 4.

## Multi-period statements

`Binder2_Redacted.pdf` contains 10 periods. Each period is its own
`extract(...)` invocation downstream — the caller is responsible for
splitting if needed. The classifier sees the *whole* PDF and emits one
layout label; per-period extraction loops over period boundaries detected
from "Statement Date" / "Statement Thru Date" pairs.

## Account-transition rows

Some Ixonia statements show a "transition row" where the account number
appears with an asterisk (e.g. `1664*`). This is a renumbering event. The
period's `account_last4` is the value WITHOUT the asterisk on the most
recent row.

## Common anomalies

- **Trailing whitespace in descriptions** — strip before output, but keep
  internal whitespace exactly (it is the contract).
- **Multi-line transaction descriptions** — Ixonia wraps descriptions onto
  the next row(s) without a date column. Merge into the prior transaction.
- **Zero-amount lines** — sometimes appear as "BEGINNING BALANCE" or
  separators. Do NOT count them in `*_count` or `*_total`.
- **Closing service charge** — appears at the very end and counts as a
  withdrawal.
- **Same-day multiple transactions** — common; do not merge.

## Reconciliation algorithm

```
expected_ending = beginning + sum(d.amount for d in deposits) - sum(w.amount for w in withdrawals)
delta = ending - expected_ending
reconciled = abs(delta) <= Decimal("0.01")
```

If `len(deposits) != deposits_count` or
`len(withdrawals) != withdrawals_count`, set `reconciled = false` even if
the balance math works — that means a row was duplicated or merged.

## When to escalate

If the model can read the summary fields but transactions don't reconcile
after two critic retries, surface `reconciled: false` in the response with
the delta. We never invent rows.

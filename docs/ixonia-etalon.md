# Ixonia Bank — etalon values

Source: `Task/task.md` (Option 4: Bank Statement Extraction Agent).
Sample file: `Task/Binder2_Redacted.pdf` (10 periods) + `Task/ixonia_binder2_ocr.txt`.

These numbers are the **contract** for the Ixonia sample. Any change to
extraction logic must keep them exact-match.

| # | Period   | Account | Deposits (count) | Deposits ($)   | Withdrawals (count) | Withdrawals ($) | Total tx |
|---|----------|---------|------------------|----------------|---------------------|-----------------|----------|
| 1 | Apr 2025 | 1664    | 81               | 1,214,254.05   | 111                 | 1,302,201.16    | 192      |
| 2 | May 2025 | 1664*   | 95               | 926,416.11     | 142                 | 1,271,197.35    | 237      |
| 3 | Jun 2024 | 1664    | 63               | 1,050,851.95   | 99                  | 1,158,172.87    | 162      |
| 4 | Jul 2024 | 4664    | 84               | 848,578.92     | 82                  | 901,281.55      | 166      |
| 5 | Aug 2024 | 4664    | 83               | 1,178,227.39   | 88                  | 939,801.97      | 171      |
| 6 | Sep 2024 | 4664    | 71               | 1,085,703.81   | 118                 | 1,143,851.49    | 189      |
| 7 | Sep 2024 | 4623    | 13               | 336,565.07     | 35                  | 336,565.07      | 48       |
| 8 | Oct 2024 | 4664    | 83               | 1,187,061.65   | 96                  | 1,168,104.30    | 179      |
| 9 | Nov 2024 | 4664*   | 75               | 847,969.53     | 120                 | 1,137,901.02    | 195      |
| 10| Dec 2024 | 4664    | 67               | 1,223,865.12   | 65                  | 835,110.45      | 132      |

Sample expected summary for period #1 (Apr 2025, account 1664):

```json
{
  "account": {"chunk_id": "period_01", "bank": "Ixonia Bank", "account_last4": "1664",
              "period": {"start": "2025-04-01", "end": "2025-04-30"}},
  "summary": {
    "chunk_id": "period_01",
    "beginning_balance": "597068.70", "ending_balance": "509121.59",
    "deposits_total": "1214254.05", "deposits_count": 81,
    "withdrawals_total": "1302201.16", "withdrawals_count": 111
  }
}
```

Note: `Account`, `Summary`, and `Transaction` all carry `chunk_id` as their first
field so the reconciler can pair fan-out results by period without relying on list
order.  API returns `Decimal` as a quoted JSON string to preserve precision; clients
should parse monetary strings with a decimal library (e.g. Python `Decimal`, JS
`decimal.js`).

## Definitions

- **`*` in the Account column.** The source PDF prints the account number
  in its masked form `XXXXXX<last4>` instead of bare `<last4>`. Confirmed
  in `Task/ixonia_binder2_ocr.txt` lines 1129 and 7588 (compare with the
  raw form on line 35). The layout classifier must not drop these periods;
  the `split_periods` deterministic node sets
  `chunk.is_account_transition = True` when the OCR `Account Number:` line
  starts with `XXXXXX`.

## Known discrepancy — row 2 (May 2025)

`Task/task.md` table writes the account for row 2 as `1664*`, but the
OCR for that period shows `XXXXXX4664`. Two interpretations:
1. Etalon-author transcribed the masked form `XXXXXX4664` as `1664*`
   (typo — should be `4664*`).
2. The masked digits in the source render ambiguously and the etalon
   author chose `1664*`.

Resolution policy (rule 7 — surface conflicts, don't average): when
implementing `extract_account`, **trust the OCR** and emit
`account_last4 = "4664"` for that period; if the eval scorer disagrees,
file a `notes[]` entry and surface to the user. Do **not** silently
patch `task.md` (Task/ is read-only).

## Edge cases worth keeping in tests

- **Period 7 (Sep 2024, account 4623)** — `Σdeposits == Σwithdrawals ==
  $336,565.07`, net change of zero, and the source has `beginning ≈ -$4.00`
  visible in the OCR. This is a legitimate zero-net statement, not a
  parsing bug. Reconciler must still pass.
- **OCR currency anomaly** — `$509, 121.59` (stray space) at line 1134
  of `Task/ixonia_binder2_ocr.txt`. Currency parser must tolerate one or
  more whitespace characters inside the number.

## Invariant

Reconciliation invariant for each period:
`beginning + Σdeposits − Σwithdrawals = ending` ± ε ($0.01).

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
  "account": {"bank": "Ixonia Bank", "account_last4": "4664",
              "period": {"start": "2025-04-01", "end": "2025-04-30"}},
  "summary": {
    "beginning_balance": 597068.70, "ending_balance": 509121.59,
    "deposits_total": 1214254.05, "deposits_count": 81,
    "withdrawals_total": 1302201.16, "withdrawals_count": 111
  }
}
```

Note: rows marked `*` in the Account column (May 2025, Nov 2024) signal an
account-number-transition row in the source PDF — the layout classifier must
not lose those periods.

Reconciliation invariant for each period:
`beginning + Σdeposits − Σwithdrawals = ending` ± ε ($0.01).

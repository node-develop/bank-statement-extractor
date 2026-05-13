# Synthetic US Business Bank Statements — Test Fixtures

5 fictional bank statements for testing OCR + agentic extraction pipelines.
All companies, account numbers, balances, and transactions are invented.

## Files

| # | PDF                                  | Quality              | Bank style            | Pages | Notes                                 |
|---|--------------------------------------|----------------------|-----------------------|-------|---------------------------------------|
| 1 | stmt_01_apex_chase.pdf               | clean_digital        | Chase                 | 1     | Vector text; baseline (easy mode)     |
| 2 | stmt_02_riverstone_bofa.pdf          | clean_digital        | Bank of America       | 2     | Vector text; multi-page continuation  |
| 3 | stmt_03_greenfield_wellsfargo.pdf    | scanned_clean        | Wells Fargo           | 1     | Image-only, 200 DPI, no rotation      |
| 4 | stmt_04_mountainpeak_pnc.pdf         | scanned_low_quality  | PNC                   | 1     | Image-only, 150 DPI, +1.2° rot, blur  |
| 5 | stmt_05_aurora_firstpacific.pdf      | scanned_degraded     | community bank        | 1     | Image-only, 110 DPI, -2.8° rot, heavy noise + uneven light |

For each PDF there is:
* `<id>.json`     — ground truth (text matches what is actually visible in the PDF)
* `<id>.ocr.txt`  — raw Tesseract 5.3 OCR transcript (PSM 6, 300 DPI render)
* `ground_truth_all.json` — all 5 ground-truths combined
* `ocr_baseline.json`     — Tesseract recall/anchor stats per statement

## Ground-truth schema

```json
{
  "id":             "stmt_01_apex_chase",
  "quality_level":  "clean_digital",
  "bank":           { "name", "short_name", "address", "phone", "website" },
  "account_holder": { "name", "address_line_1", "address_line_2" },
  "account":        { "type", "number_masked", "number_last4" },
  "period":         { "start", "end", "label" },
  "summary":        { "opening_balance", "deposits_credits",
                      "withdrawals_debits", "ending_balance" },
  "transactions":   [
    {
      "date":            "YYYY-MM-DD",
      "description":     "...",
      "amount":          1234.56,        // positive = credit, negative = debit
      "type":            "credit" | "debit",
      "running_balance": 12345.67
    }
  ]
}
```

All amounts are USD. Arithmetic invariant holds for every statement:

    ending_balance == opening_balance
                      + sum(t.amount for t in transactions if t.amount > 0)
                      - sum(-t.amount for t in transactions if t.amount < 0)
                   == transactions[-1].running_balance

The `description` field is exactly what is rendered to the page (including
any tail truncation marked with `…` when the source description didn't fit
the column width). Whitespace is normalized to single spaces because
pdftotext and every common OCR engine do the same.

## Tesseract baseline (out-of-the-box, no preprocessing)

| Statement | OCR chars | Tx recall | Field anchors hit |
|-----------|-----------|-----------|-------------------|
| stmt_01   | 2142      | 18/18     | 5/5               |
| stmt_02   | 3384      | 27/27     | 5/5               |
| stmt_03   | 2085      | 17/17     | 5/5               |
| stmt_04   | 1836      | 14/14     | 4/5               |
| stmt_05   | 1787      |  0/20     | 0/5  (by design)  |

"Tx recall" uses a forgiving token-overlap match (≥70%); the degraded
statement intentionally breaks naïve OCR so you can measure how much your
agent layer recovers vs. raw Tesseract.

## Evaluation metric suggestions

* **Field-level exact match:** bank.short_name, account.number_last4, period.start, period.end, summary.opening_balance, summary.ending_balance.
* **Transaction recall / precision:** match on (date, abs(amount)) within tolerance ±$0.01.
* **Description fuzzy match:** Levenshtein ratio ≥ 0.85 against ground-truth description.
* **Balance reconciliation:** check that extracted opening + credits − debits = extracted ending.
* **Per-tier scoring:** report metrics separately for each `quality_level` so regressions on the hard scans don't get hidden by the easy ones.

## Disclaimer

Synthetic data only. No real accounts, customers, or institutions are
represented. Bank visual styles approximate well-known issuers using only
non-trademarked typographic conventions (colors, layout); no real logos
or copyrighted assets are used.

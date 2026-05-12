Option 4: Bank Statement Extraction Agent
Sources
Goal
Build an Agent that takes a bank statement and returns its totals by periods and all transactions as structured data.

One statement in → one structured result out.
Data Source
Binder2_Redacted.pdf — original statement (Ixonia Bank, multiple periods, redacted descriptions)
ixonia_binder2_ocr.txt — OCR of the same PDF
Use either or both. We will also evaluate on unseen statements from other banks — your solution must handle them without code changes.
What you build (3–6 hours)
A function:
def extract(pdf_path: str, txt_path: str | None = None) -> dict
​
returning:
{
  "account": { "bank": "Ixonia Bank", "account_last4": "4664",
               "period": { "start": "2025-04-01", "end": "2025-04-30" } },
  "summary": {
    "beginning_balance": 597068.70, "ending_balance": 509121.59,
    "deposits_total": 1214254.05, "deposits_count": 81,
    "withdrawals_total": 1302201.16, "withdrawals_count": 111
  },
  "transactions": [
    { "date": "2025-04-01", 
      "description": "AIRLINEHYD 2759/VENDOR PMT",
      "deposit": 1809.28, 
      "withdrawal": null
     }
  ]
}
​
Plus a way to run it: CLI, HTTP endpoint, or one-field UI.
Requirements
Values must come from the document. No hallucinated numbers.
Must reconcile: beginning + Σdeposits − Σwithdrawals = ending. Flag mismatches explicitly.
Generalize to new bank layouts via prompts / acrchitecture — not code edits.
Grading
Summary fields — exact match.
Transactions — Must be reconciled with totals.
Generalization — same scoring on 2–3 unseen statements.
Deliverables
Repo link.
Short README: architecture, self-reported accuracy + known weaknesses.
30-min demo: live run on the sample + one statement you haven't seen.
Etalon results for sample
Source: Binder2_Redacted.pdf
#
**Sources**

[Binder2_Redacted.pdf](attachment:beaa5e5f-082f-41b5-b561-edaf4406520b:Binder2_Redacted.pdf)

[ixonia_binder2_ocr.txt](attachment:78f52260-f930-4fb4-b8ff-8d0a072dca69:ixonia_binder2_ocr.txt)

## Goal

Build an **Agent** that takes a bank statement and returns its **totals by periods** and **all transactions** as structured data.

One statement in → one structured result out.

## Data Source

- `Binder2_Redacted.pdf` — original statement (Ixonia Bank, multiple periods, redacted descriptions)
- `ixonia_binder2_ocr.txt` — OCR of the same PDF

Use either or both. We will also evaluate on **unseen statements from other banks** — your solution must handle them **without code changes**.

## What you build (3–6 hours)

A function:

```python
def extract(pdf_path: str, txt_path: str | None = None) -> dict
```

returning:

```json
{
  "account": { "bank": "Ixonia Bank", "account_last4": "4664",
               "period": { "start": "2025-04-01", "end": "2025-04-30" } },
  "summary": {
    "beginning_balance": 597068.70, "ending_balance": 509121.59,
    "deposits_total": 1214254.05, "deposits_count": 81,
    "withdrawals_total": 1302201.16, "withdrawals_count": 111
  },
  "transactions": [
    { "date": "2025-04-01", 
      "description": "AIRLINEHYD 2759/VENDOR PMT",
      "deposit": 1809.28, 
      "withdrawal": null
     }
  ]
}
```

Plus a way to run it: CLI, HTTP endpoint, or one-field UI.

## Requirements

- Values must come from the document. No hallucinated numbers.
- Must reconcile: `beginning + Σdeposits − Σwithdrawals = ending`. Flag mismatches explicitly.
- Generalize to new bank layouts via prompts / acrchitecture — not code edits.

## Grading

1. Summary fields — exact match.
2. Transactions — Must be reconciled with totals.
3. Generalization — same scoring on 2–3 unseen statements.

## Deliverables

1. Repo link.
2. Short README: architecture, self-reported accuracy + known weaknesses.
3. 30-min demo: live run on the sample + one statement you haven't seen.

## Etalon results for sample

**Source:** `Binder2_Redacted.pdf`

| # | Period | Account | Deposits (count) | Deposits ($) | Withdrawals (count) | Withdrawals ($) | Total tx |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Apr 2025 | 1664 | 81 | $1,214,254.05 | 111 | $1,302,201.16 | 192 |
| 2 | May 2025 | 1664* | 95 | $926,416.11 | 142 | $1,271,197.35 | 237 |
| 3 | Jun 2024 | 1664 | 63 | $1,050,851.95 | 99 | $1,158,172.87 | 162 |
| 4 | Jul 2024 | 4664 | 84 | $848,578.92 | 82 | $901,281.55 | 166 |
| 5 | Aug 2024 | 4664 | 83 | $1,178,227.39 | 88 | $939,801.97 | 171 |
| 6 | Sep 2024 | 4664 | 71 | $1,085,703.81 | 118 | $1,143,851.49 | 189 |
| 7 | Sep 2024 | 4623 | 13 | $336,565.07 | 35 | $336,565.07 | 48 |
| 8 | Oct 2024 | 4664 | 83 | $1,187,061.65 | 96 | $1,168,104.30 | 179 |
| 9 | Nov 2024 | 4664* | 75 | $847,969.53 | 120 | $1,137,901.02 | 195 |
| 10 | Dec 2024 | 4664 | 67 | $1,223,865.12 | 65 | $835,110.45 | 132 |

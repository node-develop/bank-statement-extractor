---
name: extract_summary
description: Extract the period monetary summary (beginning/ending balances, deposit and withdrawal totals and counts) from one period chunk. Structured output for the Summary model.
version: 1
model: claude-sonnet-4-6
---

## Role

You are a bank-statement summary extractor. Given text from one period chunk, locate the Balance Summary block and return a single `Summary` object. Ground every value in the text verbatim — never compute or derive balances; read them directly.

## Output schema

```
chunk_id           : string   — pass through unchanged from the input header
beginning_balance  : Decimal  — opening balance (may be negative)
ending_balance     : Decimal  — closing balance (may be negative)
deposits_total     : Decimal  — total credits this period
deposits_count     : int >= 0 — from parentheses in "Deposits and Credits (N)"
withdrawals_total  : Decimal  — total debits this period
withdrawals_count  : int >= 0 — from parentheses in "Withdrawals and Debits (N)"
```

## Source-of-truth block

Look for these lines (Ixonia layout):

```
Beginning Balance as of MM/DD/YYYY       $N,NNN.NN
+ Deposits and Credits (N)               $N,NNN.NN
- Withdrawals and Debits (N)             $N,NNN.NN
Ending Balance as of MM/DD/YYYY          $N,NNN.NN
```

The count `N` inside the parentheses is `deposits_count` / `withdrawals_count`. Do NOT count individual transaction rows — read the number from the parentheses.

Service Charges lines may appear in the balance block; they are already included in `withdrawals_count` and `withdrawals_total`. Do not add them separately.

## Currency parsing rule

Strip `$` and `,`. Collapse any internal whitespace inside the number (OCR artifacts such as `$509, 121.59` → `509121.59`). Output a string compatible with Python `Decimal` — two decimal places implied. Negative balances are valid (prefix `-`).

## Few-shot exemplar — Ixonia Apr 2025

Input:
```
chunk_id: 2025-04-01:4664

Beginning Balance as of 04/01/2025          $597,068.70
+ Deposits and Credits (81)               $1,214,254.05
- Withdrawals and Debits (111)            $1,302,201.16
Ending Balance as of 04/30/2025             $509,121.59
```

Output:
```json
{
  "chunk_id": "2025-04-01:4664",
  "beginning_balance": "597068.70",
  "ending_balance": "509121.59",
  "deposits_total": "1214254.05",
  "deposits_count": 81,
  "withdrawals_total": "1302201.16",
  "withdrawals_count": 111
}
```

## Chunk to extract

{chunk_text}

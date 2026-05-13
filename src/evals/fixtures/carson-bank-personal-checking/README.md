# carson-bank-personal-checking

## Source

- **URL:** https://www.carsonbank.com/wp-content/uploads/2021/01/Sample-Statement.pdf
- **Date downloaded:** 2026-05-13
- **License / legal note:** Public sample statement published on the Carson
  Bank website (community bank, Mulvane KS). Fictional customer
  "JOHN TEST / 123 TEST / YOUR CITY, KS 03087"; statement date "July 31, 20XX"
  (year placeholder). No real PII or signatures.
- **Provenance note:** WebFetch returned valid `%PDF-1.7` bytes (821 KB,
  6 pages). Binary cached at
  `/Users/izual/.claude/projects/-Users-izual-PycharmProjects-bank-statement-analizer/f5780384-bd3b-4b0a-b02f-50506b3d93ea/tool-results/webfetch-1778637259075-21ja12.pdf`;
  agent sandbox blocked file copy out of cache. Re-download manually with the
  URL above.

## Layout summary

Six-page community-bank personal-checking statement. Layout differs sharply
from Ixonia: (1) ACCOUNT ACTIVITY SUMMARY block with `Previous balance /
Deposits-credits (count + total) / Checks-withdrawals (count + total) / Ending
balance` instead of Ixonia's `Beginning Balance / Total Deposits / Total
Withdrawals / Ending Balance` wording; (2) TRANSACTIONS table has explicit
Debits / Credits / Balance columns (Ixonia OCR flattened to a single text
stream); (3) dedicated CHECKS table with `*` "break in sequence" annotation;
(4) DAILY BALANCE SUMMARY grid (also absent from Ixonia); (5) page 4 carries a
linked READY RESERVE line-of-credit sub-account that the period-splitter must
treat as a separate `PeriodChunk` if extracted; (6) page 6 is a printable
Account Reconciliation Form (the customer-facing pre-printed worksheet — no
transactions, must be skipped by the period-splitter). Date format
MM/DD/YYYY, US `$` currency.

## Etalon hints

Primary checking account:

| Field                     | Value         |
|---------------------------|---------------|
| Bank                      | Carson Bank   |
| Account number (last 4)   | 6547          |
| Account type              | TRUE CHECKING |
| Statement date            | July 31, 20XX |
| Previous balance          | $3,005.93     |
| Previous-balance date     | 06/28/2019    |
| Deposits / credits count  | 10            |
| Deposits / credits total  | $18,041.50    |
| Checks / withdrawals count| 54            |
| Checks / withdrawals total| $14,365.21    |
| Ending balance            | $6,682.22     |
| Ending-balance date       | 07/31/2019    |
| Statement period days     | 33            |
| Average balance           | $5,032.20     |
| Total service charge today| $6.00         |
| YTD interest              | $8.15         |
| Number of checks          | 8             |
| Total amount of checks    | $1,783.32     |

Secondary line-of-credit sub-account (separate `chunk_id` candidate):

| Field                  | Value      |
|------------------------|------------|
| Account label          | READY RESERVE |
| Account number (last 4)| 3216       |
| Previous balance       | $926.18    |
| Advances & Debits      | $0.00      |
| Payments & Credits     | $13.17     |
| New balance            | $913.01    |
| APR                    | 18.00000%  |
| Interest charged       | $14.09     |

Reconciliation invariant (primary checking):
`3,005.93 + 18,041.50 − 14,365.21 = 6,682.22` (exact, no service-charge
adjustment outside the withdrawal total).

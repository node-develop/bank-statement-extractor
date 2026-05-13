# capital-one-360-savings

## Source

- **URL:** https://ecm.capitalone.com/WCM/bank/pdfs/sample-estatement.pdf
- **Date downloaded:** 2026-05-13
- **License / legal note:** Public sample e-statement published on the Capital
  One ECM CDN. Document is watermarked SAMPLE across the page. Fictional
  customer "Savvy Saver / 360 Market St. / Anywhere, US 12345"; statement
  date 03/31/2013. No real PII.
- **Provenance note:** WebFetch returned valid `%PDF-1.6` bytes (307 KB,
  1 page).
  Re-download manually with the URL above.

## Layout summary

Single-page Capital One 360 Savings e-statement. Markedly different from
Ixonia: (1) opens with a "Since you became a Saver…" lifetime-interest header
instead of a Beginning/Ending Balance pair; (2) `Your Savings Summary`
table lists only `Account Type / Nickname / Account Number / Account Balance /
Joint Name` — no explicit deposit or withdrawal totals; (3) `Your 360 Savings
Activity` rolls into a single column with `Opening Balance`, `Monthly Interest
Paid` rows, and a `Closing Balance` row; (4) APY/APR fields surface
(`Current Interest Rate: 2.467%`, `Annual Percentage Yield Earned: 2.49%`).
Date format MM/DD/YYYY, US `$` currency. Tests the savings-account shape: the
extractor should infer `deposits_count = 3` (three interest payments) and
`withdrawals_count = 0` rather than treating "Opening/Closing Balance" rows as
transactions.

## Etalon hints

| Field                          | Value         |
|--------------------------------|---------------|
| Bank                           | Capital One 360 |
| Account product                | 360 Savings   |
| Account nickname               | Savvy Saver   |
| Account number                 | 12345678      |
| Customer number                | 46587699      |
| Statement period               | 01/01/2013 – 03/31/2013 |
| Opening balance (01/01/2013)   | $1,186.93     |
| Interest 01/31/2013            | $2.49         |
| Interest 02/28/2013            | $2.25         |
| Interest 03/31/2013            | $2.50         |
| Closing balance (03/31/2013)   | $1,194.17     |
| Deposits count (interest)      | 3             |
| Deposits total                 | $7.24         |
| Withdrawals count              | 0             |
| Withdrawals total              | $0.00         |
| Current interest rate          | 2.467%        |
| APY earned this period         | 2.49%         |
| Interest life-to-date          | $194.17       |
| Year-to-date interest          | $7.24         |

Reconciliation invariant:
`1,186.93 + 7.24 − 0.00 = 1,194.17` (exact).

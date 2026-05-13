# chase-credit-card-sample

## Source

- **URL:** https://www.chase.com/content/dam/chase-ux/documents/digital/resources/paperless_statements_chase_sample.pdf
- **Date downloaded:** 2026-05-13
- **License / legal note:** Public marketing material published by JPMorgan Chase & Co.
  on chase.com. PDF is heavily watermarked SAMPLE; carries no real customer PII
  (cardholder line literally reads "CARDHOLDER NAME / 123 MAIN STREET / CITY
  STATE 12345-1234"). Reuse for evaluation purposes is consistent with the
  document's purpose (paperless-statement marketing collateral).
- **Provenance note:** WebFetch returned valid `%PDF-1.5` bytes
  (`Title: Paperless Statement Sample`, creator `JPMorgan Chase & Co.`,
  86 KB, 1 page). The binary is cached locally at
  `/Users/izual/.claude/projects/-Users-izual-PycharmProjects-bank-statement-analizer/f5780384-bd3b-4b0a-b02f-50506b3d93ea/tool-results/webfetch-1778637197062-7835rp.pdf`
  but the agent sandbox blocked `cp`/`install`/`python shutil` from staging it
  to `sample.pdf` in this directory. Re-download manually with the URL above
  (any browser or `curl -o sample.pdf <URL>`).

## Layout summary

Single-page Chase credit-card statement with the "SAMPLE" watermark stamped
diagonally across the page. Header carries a January 2019 mini-calendar, then
two side-by-side blocks: ACCOUNT SUMMARY (Previous Balance, Payment/Credits,
Purchases, Cash Advances, Balance Transfers, Fees, Interest, New Balance) and
REWARDS SUMMARY (point balances). A YOUR ACCOUNT MESSAGES block follows, then
a tear-off remittance coupon at the bottom (PO Box 15123 Wilmington DE). The
account number is fully masked: `XXXX XXXX XXXX XXXX` in the body and `0000 0000
0000 0000` on the coupon. Distinguishes from Ixonia: no per-day transaction
rows, no running balance — credit-card schema requires `payments`/`purchases`
totals rather than `deposits`/`withdrawals` counts.

## Etalon hints

| Field                       | Value           |
|-----------------------------|-----------------|
| Statement period            | 12/03/18 – 01/01/19 |
| Previous balance            | $1,270.00       |
| Payment, Credits            | $25.00          |
| Purchases                   | $0.00           |
| Cash advances               | $0.00           |
| Balance transfers           | $0.00           |
| Fees charged                | $0.00           |
| Interest charged            | $0.00           |
| **New balance**             | $1,245.00       |
| Minimum payment due         | $25.00          |
| Payment due date            | 01/25/2019      |
| Credit limit                | $4,000.00       |
| Available credit            | $2,755.00       |
| Cash access line            | $0.00           |
| Rewards: previous balance   | 1,200           |
| Rewards: earned this period | 0               |
| Rewards: available          | 1,200           |

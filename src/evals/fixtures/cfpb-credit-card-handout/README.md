# cfpb-credit-card-handout

## Source

- **URL:** https://files.consumerfinance.gov/f/documents/cfpb_building_block_activities_sample-credit-card-statement_handout.pdf
- **Date downloaded:** 2026-05-13
- **License / legal note:** Published by the U.S. Consumer Financial Protection
  Bureau (CFPB) as a "Building Blocks" student handout (Summer 2022). CFPB
  works are U.S. federal-government publications and are in the public domain
  (17 U.S.C. 105). Document carries fictional "Susan Doe / 1234 Main Street,
  Anytown, USA" — no real PII.
- **Provenance note:** WebFetch returned valid `%PDF-1.7` bytes (58 KB,
  1 page).
  Re-download manually with the URL above.

## Layout summary

Single-page CFPB educational sample with explicit account/payment information
and a Finance Charge Summary table (Periodic Rate / APR for Purchases vs Cash
Advances). Two side-by-side tables: **Account Summary** (Previous Balance,
Payment & Credits, Purchases, Cash Advances, Balance Transfers, Fees Charged,
Interest Charged, New Balance) and **Payment Information** (New Balance,
Payment Due Date, Minimum Payment Due). Below: Opening/Closing date, Credit
Access Line, Available Credit, Cash Access Line, Available for Cash, Past Due
Amount. Differs from the Chase credit-card sample by exposing APR / periodic-
rate disclosures and using `XX` mock date placeholders (`11/27/XX – 12/26/XX`)
rather than a real year. Demonstrates the APR table layout extractors must
ignore when computing standard summary fields.

## Etalon hints

| Field                              | Value                |
|------------------------------------|----------------------|
| Account number                     | 12345-67-8907        |
| Previous balance                   | $482.42              |
| Payment, Credits                   | -$350.42             |
| Purchases                          | $1,258.56            |
| Cash advances                      | $0                   |
| Balance transfers                  | $0                   |
| Fees charged                       | $0                   |
| Interest charged                   | $2.15                |
| **New balance**                    | $1,392.71            |
| Payment due date                   | 1/23/XX              |
| Minimum payment due                | $25                  |
| Opening / Closing date             | 11/27/XX – 12/26/XX  |
| Credit access line                 | $12,000              |
| Available credit                   | $10,607.29           |
| Cash access line                   | $2,000               |
| Available for cash                 | $2,000               |
| APR (purchases)                    | 19.80%               |
| Periodic rate (purchases)          | 1.65%                |
| APR (cash advances)                | 6.48%                |
| Periodic rate (cash advances)      | 0.54%                |

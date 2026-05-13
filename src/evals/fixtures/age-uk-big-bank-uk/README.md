# age-uk-big-bank-uk

## Source

- **URL:** https://www.ageuk.org.uk/bp-assets/globalassets/wiltshire/our-services/bank-statement-sample.pdf
- **Date downloaded:** 2026-05-13
- **License / legal note:** Public educational sample published by Age UK
  Wiltshire as part of a pension-credit guidance pack. Fictional account
  holders "Mr H and Mrs E Smith"; sort code printed as `00-00-00`; account
  number `12345678`; bank labelled "Big Bank" (anonymised). No real PII.
- **Provenance note:** WebFetch returned valid `%PDF-1.5` bytes (1.3 MB,
  3 pages — first page captured for the etalon below).
  Re-download manually with the URL above.

## Layout summary

UK personal-current-account ("Flexi current account") statement, 3 pages.
Distinguishing features vs Ixonia: (1) **DD-MMM-YY date format**
(`01 Nov 19`, `15th January 2020`) — exposes US `MM/DD/YYYY` vs UK `DD MMM YY`
parsing ambiguity; (2) **Sort code** (`00-00-00`) instead of US routing
number; (3) columns labelled `Money out / Money in / Balance` (US samples use
`Withdrawals / Deposits / Balance` or `Debits / Credits / Balance`);
(4) explicit `PYMNTtype` column with UK transaction codes (`BGC`, `DEB`, `DD`,
`FPI`, `CPT`) — extractor must classify these into deposit vs withdrawal by
sign of the balance delta (assign deposit vs withdrawal by the sign of the running-balance delta); (5) coloured-bullet
annotations in the body explaining which pensions flow to which person —
purely visual, the extractor should treat them as decoration; (6) **GBP £**
currency (though the statement omits the `£` glyph from the raw text — the
extractor must not assume `$`).

## Etalon hints

| Field                  | Value                |
|------------------------|----------------------|
| Bank                   | "Big Bank" (anon.)   |
| Account holder         | Mr H and Mrs E Smith |
| Sort code              | 00-00-00             |
| Account number         | 12345678             |
| Account product        | Flexi current account|
| Statement number       | 9                    |
| Statement date         | 15 January 2020      |
| Period start (inferred)| 01 Nov 2019          |
| Period end (inferred)  | 17 Dec 2019 (page 1) |
| Currency               | GBP (£)              |

Counts and totals are not surfaced on page 1; page 1 carries ~45 transaction
rows split across `Money in` (BGC pension credits + occasional FPI) and
`Money out` (DEB Tesco / Greggs / Amazon, DD utilities, CPT Link Tesco ATM).
A full etalon requires downloading and OCRing pages 2 and 3 to obtain the
closing balance and the bank's own summary totals — defer to the evaluator script once `sample.pdf` is staged in this directory.

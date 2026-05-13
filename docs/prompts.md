# Prompt engineering log

This file tracks prompt versions and the eval delta each iteration produced.
Prompts themselves live in `src/prompts/*.md` and are loaded by name with a
version pin.

Format per entry:

```
## YYYY-MM-DD — <prompt_name> vN
- Change: <what>
- Why: <which failure mode>
- Eval before: <metric>
- Eval after: <metric>
- Verdict: keep / rollback
```

Empty until the first iteration lands.

## 2026-05-12 — classify_layout v1
- Change: initial prompt for Haiku 4.5 layout classifier; decision rubric + 2 few-shot exemplars (ixonia_business_basic, generic_us_bank).
- Why: M1 classifier node needs a versioned prompt; cache-friendly layout (stable instructions first, dynamic {chunk_text} placeholder last).
- Eval before: n/a
- Eval after: n/a (evals land in M2+ once extractors are wired)
- Verdict: keep

## 2026-05-12 — extract_account v1
- Change: initial extractor prompt for Sonnet 4.6; field rules for bank name stripping, masked/bare account_last4, and ISO 8601 period dates; 2 few-shot exemplars (Ixonia masked form, generic masked form).
- Why: M2 needs structured-output Account extraction per period chunk; masked `XXXXXX<last4>` form must strip to 4 digits, and the etalon asterisk (`4664*`) must not leak into the field.
- Eval before: n/a
- Eval after: n/a (graph wiring lands later in M2)
- Verdict: keep

## 2026-05-12 — extract_summary v1
- Change: initial extractor prompt for Sonnet 4.6; Balance Summary block parsing rules, currency whitespace-collapse for OCR anomalies, negative-balance handling, count-from-parentheses rule; 1 few-shot exemplar (Ixonia Apr 2025).
- Why: M2 needs structured-output Summary extraction; the `$509, 121.59` OCR artifact and negative beginning balances (Sep 2024 account 4623) are known edge cases that must be handled explicitly.
- Eval before: n/a
- Eval after: n/a (graph wiring lands later in M2)
- Verdict: keep

## 2026-05-12 — extract_transactions v1
- Change: initial extractor prompt for Sonnet 4.6; running-balance-delta rule (verbatim from architecture.md invariant #1), pseudo-row exclusion, multi-line stitching, currency parsing, non-negative amount discipline; 3 few-shot exemplars (single-line credit, multi-line stitch, check-number debit).
- Why: M2 needs structured-output list[Transaction] extraction; OCR column flattening makes direction assignment non-trivial — the delta rule is the only safe approach; exemplars cover the three Ixonia row shapes most likely to be mis-classified.
- Eval before: n/a
- Eval after: n/a (graph wiring lands later in M2)
- Verdict: keep

## 2026-05-13 — extract_transactions v2
- Change: added EXHAUSTIVENESS REQUIREMENT section at top of instructions (before schema): model must read deposits_count + withdrawals_count from the Balance Summary block, compute expected_total, process every row from BEGINNING BALANCE to ENDING BALANCE without stopping early, and self-check count before returning. Changed skip rule to emit null running_balance rather than skip the whole row (reduces silent row loss). Added explicit note "abbreviated for brevity; real output covers ALL rows" on the exemplars heading. Bumped version frontmatter 1→2.
- Why: Apr 2025 chunk (192 expected transactions) returned only ~12. Root cause: (1) no count anchor — model had no target to aim for; (2) exemplars showed 3 rows total, anchoring the model's structured-output path to "small list = complete"; (3) the skip-row instruction was too broad and invited omission under uncertainty. The exhaustiveness block gives Claude a concrete number to commit to and an explicit "do not stop" imperative, which is the documented pattern for forcing exhaustive list generation on Sonnet.
- Eval before: ~12 transactions extracted for Apr 2025 (etalon: 192)
- Eval after: expected ≥150, target >190
- Verdict: pending evaluator run

## 2026-05-12 — critic v1
- Change: initial critic prompt for Haiku 4.5; reconciliation invariant, diagnostic priority order (count mismatch → delta-matches-row → balance-implausible → account-hint-mismatch), CriticHint output schema, 1 few-shot exemplar.
- Why: M2 critic_loop node needs a structured hint to select which extractor of which chunk to re-run; priority ordering ensures the cheapest-to-fix cause is tried first, capping at 2 retries total.
- Eval before: n/a
- Eval after: n/a (graph wiring lands later in M2)
- Verdict: keep

---
name: reconciliation-math
description: Decimal arithmetic rules, ε tolerance, and exact reconciliation checks for bank statements. Use whenever you compute totals, compare summary fields, or write the `reconcile` node. Do NOT use float for money.
---

# Reconciliation math

## Decimal hygiene

```python
from decimal import Decimal, getcontext, ROUND_HALF_EVEN
getcontext().rounding = ROUND_HALF_EVEN
EPSILON = Decimal("0.01")
```

- Parse amounts from strings: `Decimal("1,234.56".replace(",", ""))`.
- **Never** `Decimal(1234.56)` (binary float → wrong value).
- Compare with `abs(a - b) <= EPSILON`, not `==`.

## The three invariants

For each period:

1. `sum(d.amount for d in deposits) == summary.deposits_total`
2. `sum(w.amount for w in withdrawals) == summary.withdrawals_total`
3. `summary.beginning_balance + summary.deposits_total - summary.withdrawals_total == summary.ending_balance`

All three must hold for `reconciled = true`. Any failure populates a
human-readable `notes[]` entry and sets `reconciled = false`.

## Counts

```python
assert summary.deposits_count == len([t for t in transactions if t.deposit is not None])
assert summary.withdrawals_count == len([t for t in transactions if t.withdrawal is not None])
```

Mismatched counts are the canary for merged or split rows.

## Sample test

```python
def test_reconcile_ixonia_apr_2025():
    state = run_extract("Task/Binder2_Redacted.pdf", period="2025-04")
    r = state["reconciliation"]
    assert r.reconciled
    assert r.delta == Decimal("0.00")
    s = state["summary"]
    assert s.deposits_total == Decimal("1214254.05")
    assert s.deposits_count == 81
    assert s.withdrawals_total == Decimal("1302201.16")
    assert s.withdrawals_count == 111
    assert s.beginning_balance == Decimal("597068.70")
    assert s.ending_balance == Decimal("509121.59")
```

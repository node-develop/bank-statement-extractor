---
name: langsmith-tracing
description: How to attach run name, tags, and metadata to LangGraph runs so eval reports are searchable in LangSmith. Use whenever adding a node, endpoint, or eval script that should be observable. Do NOT use for prompt design.
---

# LangSmith tracing conventions

## Env

```
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=bank-statement-analizer-${ENV}   # dev | prod
LANGSMITH_TRACING=true
```

## Per-run metadata

```python
from langsmith import traceable

config = {
    "run_name": f"{bank_slug}:{period.isoformat()}",
    "tags": ["extract", bank_slug],
    "metadata": {
        "statement_sha256": statement_hash,
        "statement_pages": page_count,
        "total_tx_expected": expected_count,
        "ENV": ENV,
    },
}
result = graph.invoke(state, config=config)
```

## Datasets

- `ixonia-binder2` — 10 examples, one per period, etalon from `docs/ixonia-etalon.md`.
- `holdout-banks` — grow as we collect unseen statements. Each example
  carries the etalon `summary` in `outputs`.

## Custom scorers

`src/evals/scorers.py` exposes:

- `summary_exact_match(run, example) -> bool` — every summary field matches.
- `reconciled(run, example) -> bool` — `reconciliation.reconciled` is true.
- `tx_count_match(run, example) -> bool` — `len(transactions)` equals etalon.

Wire these into the LangSmith eval CLI:

```
uv run langsmith eval src/evals/ixonia.py --scorers summary_exact_match,reconciled,tx_count_match
```

## Rules

1. **Every node logs via `@traceable`** or via LangChain's built-in
   `with_config(...)`. No silent nodes — that defeats observability.
2. **Run name is deterministic.** `f"{bank_slug}:{period}"` lets you grep
   in LangSmith. Don't use `datetime.now()` in run names.
3. **Don't put PII in tags.** Tags are global-search-indexed. Statement
   hashes and bank slugs only.

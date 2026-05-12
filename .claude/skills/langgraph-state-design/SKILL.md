---
name: langgraph-state-design
description: How to design LangGraph state for bank-statement extraction — TypedDict shape, Annotated reducers, parallel branch merging, checkpointer choice. Use when adding/changing state fields, wiring parallel nodes, or debugging "channel not found" / merge errors. Do NOT use for prompt design.
---

# LangGraph state design

## Shape

The graph state is a `TypedDict` with explicit reducers on fields that may
be written by multiple nodes (parallel branches) or appended to over time.

```python
from typing import Annotated, Literal, TypedDict
from operator import add
from src.models import RawStatement, Account, Summary, Transaction, Reconciliation

def extend(left: list, right: list) -> list:
    return left + right

class GraphState(TypedDict):
    pdf_path: str
    txt_path: str | None
    raw: RawStatement
    layout: Literal["ixonia_business_basic", "generic_us_bank", "unknown"]
    account: Account | None
    summary: Summary | None
    transactions: Annotated[list[Transaction], extend]
    reconciliation: Reconciliation | None
    retry_count: int
    errors: Annotated[list[str], extend]
```

## Rules

1. **One reducer per merging field.** Without a reducer, parallel writes
   raise `InvalidUpdateError`. With a wrong reducer (e.g. `add` for ints
   when you want last-write-wins), state silently corrupts.
2. **Optional fields default to `None`, not `{}`/`[]`.** A `None` summary
   is a signal that the node hasn't run yet; an empty dict is ambiguous.
3. **Never mutate state in place.** Return a partial dict from each node.
   LangGraph merges via reducers; mutation breaks checkpoint replay.
4. **`retry_count` is a plain int** — the critic_loop bumps it and the
   conditional edge gates on it.
5. **Avoid `dict[str, Any]` blobs.** Make a pydantic model. The schema is
   the contract; opaque blobs defeat type checking and LangSmith filtering.

## Parallel branches

```python
g.add_node("extract_account", extract_account)
g.add_node("extract_summary", extract_summary)
g.add_node("extract_transactions", extract_transactions)
g.add_node("merge_state", merge_state)

g.add_edge("classify_layout", "extract_account")
g.add_edge("classify_layout", "extract_summary")
g.add_edge("classify_layout", "extract_transactions")
g.add_edge("extract_account", "merge_state")
g.add_edge("extract_summary", "merge_state")
g.add_edge("extract_transactions", "merge_state")
```

LangGraph runs the three extractors concurrently. `merge_state` is a
join — it waits for all three before firing.

## Checkpointer

- Dev: `SqliteSaver.from_conn_string("./graph.sqlite")`.
- Prod: `PostgresSaver.from_conn_string(os.environ["DATABASE_URL"])`.
- Always wire a `thread_id` (use the statement sha256). Without
  `thread_id`, checkpoints are useless.

## Common mistakes

- Forgetting `Annotated[..., reducer]` on a list/dict that two nodes
  write. Symptom: `InvalidUpdateError: At key '<field>' two updates were applied`.
- Storing a non-serializable object (e.g. an `httpx.AsyncClient`) in
  state. Symptom: checkpointer crash on save. Fix: pass it via builder
  closure, not state.

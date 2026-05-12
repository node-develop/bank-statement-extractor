"""LangGraph state for the bank-statement-analizer extraction pipeline.

Multi-period invariant
----------------------
Every list-shaped field (``layouts``, ``accounts``, ``summaries``,
``transactions``, ``reconciliations``) accumulates one entry per period chunk
as the graph fans out via the LangGraph ``Send`` API.  When the graph reaches
``finalize``, each list has exactly ``len(period_chunks)`` entries (one per
chunk), keyed by the ``chunk_id`` carried inside each model.  The ``errors``
list accumulates across all nodes — any node may append without overwriting
entries from other branches.

Reducer strategy
----------------
All accumulating lists use ``Annotated[list[T], operator.add]``.  This is the
standard LangGraph pattern: when a node returns ``{"accounts": [new_account]}``,
the reducer appends it to the existing list rather than replacing it.
``operator.add`` on two lists is equivalent to ``left + right``.

Non-list scalar fields (``pdf_path``, ``txt_path``, ``raw``, ``retry_count``)
are plain TypedDict fields with last-write-wins semantics, which is correct
because only one node writes each of them.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, NotRequired, TypedDict

# LangGraph's StateGraph calls `typing.get_type_hints()` on the TypedDict at
# compile time, so the M0 models referenced in field annotations below must
# be importable at runtime — not gated behind TYPE_CHECKING.
from src.models import (  # noqa: TC001 — runtime-required by LangGraph TypedDict introspection
    Account,
    ExtractResult,
    LayoutLabel,
    PeriodChunk,
    RawStatement,
    Reconciliation,
    Summary,
    Transaction,
)

# Note on ``pending_hint``: the real runtime type is
# ``src.nodes.critic_loop.CriticHint`` (a Pydantic BaseModel), but importing
# it here would create a circular dependency (critic_loop imports GraphState).
# We type it as ``Any`` and document the contract in the field docstring.

__all__ = ["GraphState"]


def _reduce_by_chunk_id(left: list[Any], right: list[Any]) -> list[Any]:
    """Reducer for lists that may carry one entry per ``chunk_id``.

    Default LangGraph reducer ``operator.add`` appends, which is correct for
    fan-out where each branch contributes a unique ``chunk_id``.  But the
    critic loop re-runs ``reconcile`` on retry passes, which would otherwise
    cause the ``reconciliations`` list to accumulate duplicate entries for the
    same ``chunk_id`` (rule 12 — silent structural duplication).

    Semantics: last-write-wins by ``chunk_id``, preserving the order of first
    appearance.  Used only for ``reconciliations`` in this milestone; M3 will
    extend it to the extractor lists when extractor retries land.
    """
    merged: dict[str, Any] = {x.chunk_id: x for x in left}
    for x in right:
        merged[x.chunk_id] = x
    return list(merged.values())


class GraphState(TypedDict):
    """Shared state threaded through every node of the extraction graph.

    Fields
    ------
    pdf_path:
        Absolute path to the uploaded PDF file.
    txt_path:
        Optional absolute path to the companion OCR text file.
    raw:
        Populated by ``ingest``. Contains per-page PDF text (post source-
        selection policy), optional OCR dump, SHA-256 of the PDF bytes, and
        page count.
    period_chunks:
        Populated by ``split_periods``.  One ``PeriodChunk`` per detected
        statement period.  This is a plain list (not a reducer) because
        ``split_periods`` is the single writer.
    layouts:
        Accumulated by ``classify_layout`` fan-out branches.  One
        ``LayoutLabel`` per chunk (carries ``chunk_id``).
    accounts:
        Accumulated by ``extract_account`` fan-out branches.  One ``Account``
        per chunk.
    summaries:
        Accumulated by ``extract_summary`` fan-out branches.  One ``Summary``
        per chunk.
    transactions:
        Accumulated by ``extract_transactions`` fan-out branches.  All
        ``Transaction`` objects across all periods are collected into a single
        flat list; downstream nodes filter by ``chunk_id`` where needed.
    reconciliations:
        Accumulated by ``reconcile`` (one pass per chunk).  One
        ``Reconciliation`` per chunk (carries ``chunk_id``).
    retry_count:
        Incremented by ``critic_loop`` on each retry pass; caps at 2.
    errors:
        Accumulated by any node that encounters a non-fatal problem (OCR
        disagreement, regex miss on period boundary, etc.).  Never cleared.
    pending_hint:
        Set by ``critic`` when it diagnoses a reconciliation failure.
        Runtime type is ``src.nodes.critic_loop.CriticHint``; annotated as
        ``Any`` here to avoid a circular import.  ``NotRequired`` — absent
        until the first critic invocation.  Read by M3 retry-extractor
        nodes (not yet wired in M2 R3).
    final:
        Populated by ``finalize`` as the last step.  ``NotRequired`` so that
        all intermediate state snapshots remain valid before finalize runs.
    """

    pdf_path: str
    txt_path: str | None
    raw: RawStatement
    period_chunks: list[PeriodChunk]
    layouts: Annotated[list[LayoutLabel], operator.add]
    accounts: Annotated[list[Account], operator.add]
    summaries: Annotated[list[Summary], operator.add]
    transactions: Annotated[list[Transaction], operator.add]
    reconciliations: Annotated[list[Reconciliation], _reduce_by_chunk_id]
    retry_count: int
    errors: Annotated[list[str], operator.add]
    pending_hint: NotRequired[Any]
    final: NotRequired[ExtractResult]

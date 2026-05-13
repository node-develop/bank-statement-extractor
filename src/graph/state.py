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
from decimal import Decimal  # noqa: TC003 — runtime annotation in cumulative_cost_usd field
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
    VerifierReport,
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


def _add_decimal(left: Decimal, right: Decimal) -> Decimal:
    """Reducer for ``cumulative_cost_usd`` — plain Decimal addition."""
    return left + right


def _reduce_rows_by_chunk_id(left: list[Any], right: list[Any]) -> list[Any]:
    """Reducer for ``transactions`` — replace all rows for a chunk_id on retry.

    Unlike ``_reduce_by_chunk_id`` (one entry per chunk_id), this reducer
    expects MANY rows per chunk_id (192 transactions on Ixonia period_01,
    say).  Semantics: when the ``right`` side contains any rows for a given
    chunk_id, drop ALL rows for that chunk_id from ``left`` and append the
    new rows.  Other chunk_ids in ``left`` pass through untouched.

    Without this, ``operator.add`` accumulates duplicates across critic-retry
    extractor reruns: the second pass for period_01 appends another 192 rows
    on top of the original 192, so verifier sees 384 rows, C3 ``duplicate_row``
    and C1 ``balance_chain_break`` fire spuriously, and cost balloons.
    """
    if not right:
        return list(left)
    overwritten_chunks = {row.chunk_id for row in right}
    keep_left = [row for row in left if row.chunk_id not in overwritten_chunks]
    return keep_left + list(right)


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
        until the first critic invocation.  Read by apply_critic_hint
        to dispatch one extractor re-run per hint.
    final:
        Populated by ``finalize`` as the last step.  ``NotRequired`` so that
        all intermediate state snapshots remain valid before finalize runs.
    verifier_reports:
        Phase 2 — verifier reports, one per chunk_id. ``_reduce_by_chunk_id``
        so that re-extraction passes (Phase 3 critic loop) overwrite, not
        append.
    cumulative_cost_usd:
        Phase 3 — running sum of all LLM call costs in USD.  ``_add_decimal``
        reducer accumulates per-call deltas returned by every LLM-using node.
        Initial state MUST set this to ``Decimal("0")``.
    human_corrections:
        Phase 4 — corrections submitted via POST /review/{id}.  Runtime type
        is ``list[TransactionCorrection]``; typed ``Any`` here to avoid a
        circular import with the Phase 4 model.  Last-write-wins (NotRequired).
    force_resume:
        Phase 4 — True when the human reviewer opts to bypass re-extraction
        and accept the current result as-is.  Last-write-wins (NotRequired).
    pending_review:
        Phase 4 — set by ``await_review`` when ``interrupt()`` fires, marking
        that this thread is waiting for human input.  Last-write-wins
        (NotRequired).
    review_payload:
        Phase 4 — JSON-serialisable payload surfaced to the human via
        ``interrupt()``.  Last-write-wins (NotRequired).
    """

    pdf_path: str
    txt_path: str | None
    raw: RawStatement
    period_chunks: list[PeriodChunk]
    layouts: Annotated[list[LayoutLabel], operator.add]
    accounts: Annotated[list[Account], operator.add]
    summaries: Annotated[list[Summary], operator.add]
    transactions: Annotated[list[Transaction], _reduce_rows_by_chunk_id]
    reconciliations: Annotated[list[Reconciliation], _reduce_by_chunk_id]
    retry_count: int
    errors: Annotated[list[str], operator.add]
    pending_hint: NotRequired[Any]
    final: NotRequired[ExtractResult]
    # Phase 2 — verifier reports, one per chunk_id. ``_reduce_by_chunk_id`` so
    # that re-extraction passes (Phase 3 critic loop) overwrite, not append.
    verifier_reports: Annotated[list[VerifierReport], _reduce_by_chunk_id]
    # Phase 3 — cost ceiling tracking.  operator.add on Decimal is associative.
    # Initial state MUST set this to Decimal("0") at all invocation sites.
    cumulative_cost_usd: Annotated[Decimal, _add_decimal]
    # Phase 4 — HITL fields (all NotRequired, last-write-wins).
    # ``human_corrections`` runtime type is list[TransactionCorrection]; typed
    # Any here to avoid circular import — Phase 4 defines the real model.
    human_corrections: NotRequired[list[Any]]
    force_resume: NotRequired[bool]
    pending_review: NotRequired[bool]
    review_payload: NotRequired[dict[str, Any]]

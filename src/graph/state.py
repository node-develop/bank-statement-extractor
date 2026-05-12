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
from typing import TYPE_CHECKING, Annotated, TypedDict

if TYPE_CHECKING:
    from src.models import (
        Account,
        LayoutLabel,
        PeriodChunk,
        RawStatement,
        Reconciliation,
        Summary,
        Transaction,
    )

__all__ = ["GraphState"]


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
    """

    pdf_path: str
    txt_path: str | None
    raw: RawStatement
    period_chunks: list[PeriodChunk]
    layouts: Annotated[list[LayoutLabel], operator.add]
    accounts: Annotated[list[Account], operator.add]
    summaries: Annotated[list[Summary], operator.add]
    transactions: Annotated[list[Transaction], operator.add]
    reconciliations: Annotated[list[Reconciliation], operator.add]
    retry_count: int
    errors: Annotated[list[str], operator.add]

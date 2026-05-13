"""``merge_state`` graph node — join point after the per-chunk fan-out.

Because ``GraphState`` uses ``Annotated[list, operator.add]`` reducers,
LangGraph has already merged all per-chunk results into the accumulating lists
by the time this node is reached.  ``merge_state`` is therefore a **no-op
pass-through** that exists solely so the builder has a single named join point
before ``reconcile``.

Responsibilities:
- Log per-chunk arrival counts at INFO for traceability.
- Verify that each accumulating list contains exactly ``len(period_chunks)``
  entries; if not, append a specific error to ``errors[]``.
- Return ``{}`` (empty delta) when counts are balanced; ``{"errors": [...]}``
  otherwise.
"""

from __future__ import annotations

from typing import Any

from src.api.logging import get_logger
from src.graph.state import GraphState  # noqa: TC001 — runtime-required by LangGraph

logger = get_logger(__name__)


def merge_state(state: GraphState) -> dict[str, Any]:
    """Verify fan-out completion and log counts; return empty state delta.

    Parameters
    ----------
    state:
        The full ``GraphState`` after the per-chunk fan-out branches have
        been merged by LangGraph's ``operator.add`` reducers.

    Returns
    -------
    dict
        ``{}`` when all lists are balanced (no errors injected).
        ``{"errors": [str, ...]}`` when any list count mismatches.
    """
    expected = len(state["period_chunks"])
    chunk_ids = [c.chunk_id for c in state["period_chunks"]]

    accounts_n = len(state.get("accounts", []))
    summaries_n = len(state.get("summaries", []))
    layouts_n = len(state.get("layouts", []))

    logger.info(
        "merge_state: expected=%d  accounts=%d  summaries=%d  layouts=%d  transactions=%d",
        expected,
        accounts_n,
        summaries_n,
        layouts_n,
        len(state.get("transactions", [])),
    )

    errors: list[str] = []

    def _check(list_name: str, actual: int) -> None:
        if actual != expected:
            # Identify which chunk_ids are missing by comparing against
            # the present chunk_ids in the list.
            errors.append(
                f"merge_state: list '{list_name}' has {actual} entries "
                f"but expected {expected} (period_chunks={chunk_ids})"
            )

    _check("accounts", accounts_n)
    _check("summaries", summaries_n)
    _check("layouts", layouts_n)

    if errors:
        for msg in errors:
            logger.warning(msg)
        return {"errors": errors}

    return {}

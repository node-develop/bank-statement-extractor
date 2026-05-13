"""HITL review endpoints (PRD §5.2).

GET  /pending_review              — list rows in status='pending'
GET  /review/{extraction_id}      — full payload + suspects + chunk excerpts
POST /review/{extraction_id}      — submit corrections; resume the paused graph

The POST handler reads the row's ``thread_id`` from ``reviews.sqlite``,
calls ``await graph.ainvoke(Command(resume={...}), config={"thread_id": ...})``
to resume the paused LangGraph thread, marks the row ``resolved`` on success,
and returns the final ``ExtractResult``.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from langgraph.types import Command
from pydantic import BaseModel, Field

from src.api import reviews
from src.api.logging import get_logger
from src.models import ExtractResult, TransactionCorrection

logger = get_logger(__name__)

router = APIRouter(tags=["reviews"])


class _ReviewSubmission(BaseModel):
    """Body for POST /review/{extraction_id}."""

    corrections: list[TransactionCorrection] = Field(default_factory=list)
    force: bool = False


class _PendingReviewSummary(BaseModel):
    extraction_id: str
    statement_sha256: str
    created_at: str
    suspect_count: int
    status: Literal["pending", "in_review", "resolved", "aborted"]
    reason: str | None = None


@router.get("/pending_review", response_model=list[_PendingReviewSummary])
def list_pending_reviews() -> list[dict[str, Any]]:
    """Return up to 50 most-recent pending review rows (any status)."""
    return reviews.list_pending(limit=50)


@router.get("/review/{extraction_id}")
def get_pending_review(extraction_id: str) -> dict[str, Any]:
    """Return one review's full payload (suspects + chunk excerpts)."""
    row = reviews.get_review(extraction_id)
    if row is None:
        raise HTTPException(status_code=404, detail="extraction_id not found")
    # Mark as in_review on first read (optimistic concurrency).
    if row["status"] == "pending":
        reviews.mark_in_review(extraction_id)
        row["status"] = "in_review"
    return row


@router.post("/review/{extraction_id}", response_model=ExtractResult)
async def submit_review(
    extraction_id: str,
    body: _ReviewSubmission,
    request: Request,
) -> ExtractResult:
    """Resume the paused graph with the human's corrections."""
    row = reviews.get_review(extraction_id)
    if row is None:
        raise HTTPException(status_code=404, detail="extraction_id not found")
    if row["status"] not in ("pending", "in_review"):
        raise HTTPException(
            status_code=409,
            detail=f"review status is {row['status']!r}; cannot submit",
        )

    thread_id = row["thread_id"]
    resume_payload: dict[str, Any] = {
        "corrections": [c.model_dump() for c in body.corrections],
        "force": body.force,
    }

    graph = request.app.state.graph
    config: dict[str, Any] = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 50,
    }

    logger.info(
        "review: resuming thread_id=%s extraction_id=%s force=%s n_corrections=%d",
        thread_id,
        extraction_id,
        body.force,
        len(body.corrections),
    )

    result_state: dict[str, Any] = await graph.ainvoke(
        Command(resume=resume_payload), config=config
    )

    # The graph either completes (final present) or pauses again (interrupt).
    if "final" not in result_state:
        # Re-pause: keep the row open so a follow-up POST is possible.
        raise HTTPException(
            status_code=409,
            detail="graph re-paused after resume; corrections did not finalise",
        )

    reviews.mark_resolved(extraction_id)
    extract_result: ExtractResult = result_state["final"]
    return extract_result

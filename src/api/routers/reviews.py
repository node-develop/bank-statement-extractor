"""HITL review endpoints.

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
        # Re-pause: insert a NEW pending_reviews row with the new interrupt
        # payload — re-pause produces a new extraction_id — and mark the prior
        # row resolved so it doesn't show up as a stale duplicate.
        # Surface the new id to the caller via a 409 response detail so the
        # frontend can re-fetch /review/{new_extraction_id}.
        from uuid import uuid4

        interrupts: Any = result_state.get("__interrupt__", [])
        new_payload: dict[str, Any] = (
            interrupts[0].value if interrupts and hasattr(interrupts[0], "value") else {}
        )
        new_extraction_id = str(uuid4())
        reviews.insert_pending(
            extraction_id=new_extraction_id,
            thread_id=thread_id,
            statement_sha256=row["statement_sha256"],
            suspect_count=len(new_payload.get("suspects", [])),
            reason=new_payload.get("reason"),
            review_payload=new_payload,
        )
        reviews.mark_resolved(extraction_id)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "graph re-paused after resume",
                "new_extraction_id": new_extraction_id,
                "reason": new_payload.get("reason"),
            },
        )

    reviews.mark_resolved(extraction_id)
    extract_result: ExtractResult = result_state["final"]
    return extract_result

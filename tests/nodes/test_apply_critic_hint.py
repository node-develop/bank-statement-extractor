"""Unit tests for src/nodes/apply_critic_hint.py — PRD §4.2.2.

Three scenarios per the PRD:
1. happy path — one Send dispatched with hint prepended to BOTH pdf_text and ocr_slice
2. missing pending_hint — returns []
3. unknown chunk_id in hint — returns []
"""

from __future__ import annotations

from typing import Any

from src.models import PeriodChunk
from src.nodes.apply_critic_hint import apply_critic_hint
from src.nodes.critic_loop import CriticHint


def _chunk(chunk_id: str = "period_01") -> PeriodChunk:
    return PeriodChunk(
        chunk_id=chunk_id,
        page_range=(1, 2),
        pdf_text="ORIGINAL_PDF_TEXT",
        ocr_slice="ORIGINAL_OCR_TEXT",
        account_hint_last4="1664",
    )


def _state(*, chunks: list[PeriodChunk], hint: CriticHint | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "pdf_path": "/tmp/x.pdf",
        "txt_path": None,
        "period_chunks": chunks,
        "layouts": [],
        "accounts": [],
        "summaries": [],
        "transactions": [],
        "reconciliations": [],
        "verifier_reports": [],
        "retry_count": 0,
        "errors": [],
    }
    if hint is not None:
        out["pending_hint"] = hint
    return out


def test_apply_critic_hint_dispatches_one_send() -> None:
    """Happy path: returns exactly one Send for the hinted extractor + chunk,
    with the hint block prepended to BOTH pdf_text and ocr_slice."""
    chunk = _chunk("period_01")
    hint = CriticHint(
        chunk_id="period_01",
        extractor="extract_transactions",
        hint="re-check row 5 amount",
    )
    state = _state(chunks=[chunk], hint=hint)

    sends = apply_critic_hint(state)

    assert len(sends) == 1
    send = sends[0]
    # Send is a langgraph object; access via its public attrs.
    assert send.node == "extract_transactions"
    annotated_chunk: PeriodChunk = send.arg
    assert annotated_chunk.chunk_id == "period_01"
    # Hint block prepended to BOTH text sources (PRD §5.5 dual-injection).
    assert "Critic hint" in annotated_chunk.pdf_text
    assert "re-check row 5 amount" in annotated_chunk.pdf_text
    assert annotated_chunk.pdf_text.endswith("ORIGINAL_PDF_TEXT")
    assert annotated_chunk.ocr_slice is not None
    assert "Critic hint" in annotated_chunk.ocr_slice
    assert "re-check row 5 amount" in annotated_chunk.ocr_slice
    assert annotated_chunk.ocr_slice.endswith("ORIGINAL_OCR_TEXT")


def test_apply_critic_hint_missing_hint_returns_empty() -> None:
    """When pending_hint is absent, returns [] (graph short-circuits to merge)."""
    state = _state(chunks=[_chunk("period_01")], hint=None)
    assert apply_critic_hint(state) == []


def test_apply_critic_hint_unknown_chunk_returns_empty() -> None:
    """When the hint references a chunk_id not in period_chunks, returns []."""
    chunk = _chunk("period_01")
    hint = CriticHint(
        chunk_id="period_99",  # not in state
        extractor="extract_summary",
        hint="anything",
    )
    state = _state(chunks=[chunk], hint=hint)
    assert apply_critic_hint(state) == []

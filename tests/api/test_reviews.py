"""Tests for the HITL review endpoints (Phase 4 — PRD §5.8).

All tests use ``starlette.testclient.TestClient`` and an in-memory mock
of the LangGraph graph + an ephemeral SQLite reviews DB written under
``tmp_path`` (REVIEWS_DB_PATH env override).
"""

from __future__ import annotations

import io
from pathlib import Path  # noqa: TC003 — runtime-required by tmp_path fixture annotation
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Stub PDF (minimal valid header for content-type check)
# ---------------------------------------------------------------------------

_STUB_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


@pytest.fixture()
def client_with_paused_graph(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Yield (TestClient, mock_graph) where /extract returns __interrupt__.

    The reviews DB is written to ``tmp_path/reviews.sqlite`` so tests are
    isolated and don't touch any real path.
    """
    monkeypatch.setenv("REVIEWS_DB_PATH", str(tmp_path / "reviews.sqlite"))

    import src.api.main as api_main

    # Mock interrupt-style result: no 'final', '__interrupt__' carries the payload.
    interrupt_obj = MagicMock()
    interrupt_obj.value = {
        "suspects": [{"chunk_id": "period_01", "row_index": 0}],
        "reason": "suspects_exceeded",
        "partial_periods": [],
    }
    paused_state = {
        "__interrupt__": [interrupt_obj],
        "errors": [],
    }

    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(return_value=paused_state)

    monkeypatch.setattr("src.api.main.build_graph", lambda checkpointer=None: fake_graph)

    async def _fake_async_checkpointer() -> tuple[MagicMock, Any]:
        async def _noop() -> None:
            return None

        return MagicMock(), _noop

    monkeypatch.setattr("src.api.main.build_async_checkpointer", _fake_async_checkpointer)

    app = api_main.create_app()
    with TestClient(app) as client:
        yield client, fake_graph


# ---------------------------------------------------------------------------
# Test 1: empty initial state — GET /pending_review returns []
# ---------------------------------------------------------------------------


def test_list_pending_reviews_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("REVIEWS_DB_PATH", str(tmp_path / "reviews.sqlite"))
    import src.api.main as api_main

    fake_graph = MagicMock()
    monkeypatch.setattr("src.api.main.build_graph", lambda checkpointer=None: fake_graph)

    async def _fake_cp() -> tuple[MagicMock, Any]:
        async def _noop() -> None:
            return None

        return MagicMock(), _noop

    monkeypatch.setattr("src.api.main.build_async_checkpointer", _fake_cp)

    app = api_main.create_app()
    with TestClient(app) as client:
        resp = client.get("/pending_review")
        assert resp.status_code == 200
        assert resp.json() == []


# ---------------------------------------------------------------------------
# Test 2: paused extract → /pending_review lists the new row
# ---------------------------------------------------------------------------


def test_extract_emits_pending_review_when_paused(client_with_paused_graph: Any) -> None:
    client, _ = client_with_paused_graph
    response = client.post(
        "/extract",
        files={"file": ("statement.pdf", io.BytesIO(_STUB_PDF), "application/pdf")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pending_review"] is not None
    assert body["pending_review"]["reason"] == "suspects_exceeded"
    assert body["pending_review"]["suspect_count"] == 1
    extraction_id = body["pending_review"]["extraction_id"]
    assert isinstance(extraction_id, str) and len(extraction_id) > 0

    # GET /pending_review now lists this row.
    resp = client.get("/pending_review")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["extraction_id"] == extraction_id


# ---------------------------------------------------------------------------
# Test 3: GET /review/{id} returns full payload + transitions to in_review
# ---------------------------------------------------------------------------


def test_get_review_returns_payload_and_marks_in_review(
    client_with_paused_graph: Any,
) -> None:
    client, _ = client_with_paused_graph
    body = client.post(
        "/extract",
        files={"file": ("s.pdf", io.BytesIO(_STUB_PDF), "application/pdf")},
    ).json()
    extraction_id = body["pending_review"]["extraction_id"]

    resp = client.get(f"/review/{extraction_id}")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["extraction_id"] == extraction_id
    assert payload["status"] == "in_review"
    assert "review_payload" in payload
    assert payload["review_payload"]["reason"] == "suspects_exceeded"


def test_get_review_404_for_unknown_id(client_with_paused_graph: Any) -> None:
    client, _ = client_with_paused_graph
    resp = client.get("/review/not-a-real-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test 4: POST /review/{id} resumes the graph; on success → resolved
# ---------------------------------------------------------------------------


def test_post_review_resumes_graph_to_finalize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Submit corrections; the second graph.ainvoke returns 'final'."""
    monkeypatch.setenv("REVIEWS_DB_PATH", str(tmp_path / "reviews.sqlite"))

    from datetime import date
    from decimal import Decimal

    import src.api.main as api_main
    from src.models import (
        Account,
        ExtractResult,
        Period,
        PeriodResult,
        Reconciliation,
        Summary,
    )

    interrupt_obj = MagicMock()
    interrupt_obj.value = {
        "suspects": [{"chunk_id": "period_01", "row_index": 0}],
        "reason": "suspects_exceeded",
        "partial_periods": [],
    }
    paused_state = {"__interrupt__": [interrupt_obj], "errors": []}

    final_etalon = ExtractResult(
        periods=[
            PeriodResult(
                chunk_id="period_01",
                account=Account(
                    chunk_id="period_01",
                    bank="Ixonia Bank",
                    account_last4="1664",
                    period=Period(start=date(2025, 4, 1), end=date(2025, 4, 30)),
                ),
                summary=Summary(
                    chunk_id="period_01",
                    beginning_balance=Decimal("597068.70"),
                    ending_balance=Decimal("509121.59"),
                    deposits_total=Decimal("1214254.05"),
                    deposits_count=81,
                    withdrawals_total=Decimal("1302201.16"),
                    withdrawals_count=111,
                ),
                transactions=[],
                layout="ixonia_business_basic",
                reconciliation=Reconciliation(
                    chunk_id="period_01",
                    reconciled=True,
                    delta=Decimal("0.00"),
                    notes=[],
                ),
            )
        ],
        statement_sha256="b" * 64,
    )
    final_state = {"final": final_etalon}

    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(side_effect=[paused_state, final_state])
    monkeypatch.setattr("src.api.main.build_graph", lambda checkpointer=None: fake_graph)

    async def _fake_cp() -> tuple[MagicMock, Any]:
        async def _noop() -> None:
            return None

        return MagicMock(), _noop

    monkeypatch.setattr("src.api.main.build_async_checkpointer", _fake_cp)

    app = api_main.create_app()
    with TestClient(app) as client:
        # 1. /extract pauses
        body = client.post(
            "/extract",
            files={"file": ("s.pdf", io.BytesIO(_STUB_PDF), "application/pdf")},
        ).json()
        extraction_id = body["pending_review"]["extraction_id"]

        # 2. POST /review/{id} resumes — second ainvoke returns final.
        resp = client.post(
            f"/review/{extraction_id}",
            json={
                "corrections": [
                    {
                        "chunk_id": "period_01",
                        "row_index": 5,
                        "action": "edit",
                        "fields": {"amount": "1809.28"},
                    }
                ],
                "force": False,
            },
        )
        assert resp.status_code == 200, resp.text
        result = resp.json()
        assert len(result["periods"]) == 1
        assert result["periods"][0]["reconciliation"]["reconciled"] is True

        # 3. The row is now marked resolved.
        listed = client.get("/pending_review").json()
        row = next(r for r in listed if r["extraction_id"] == extraction_id)
        assert row["status"] == "resolved"


# ---------------------------------------------------------------------------
# Test 5: 404 on POST to unknown id
# ---------------------------------------------------------------------------


def test_post_review_404_for_unknown_id(client_with_paused_graph: Any) -> None:
    client, _ = client_with_paused_graph
    resp = client.post(
        "/review/not-a-real-id",
        json={"corrections": [], "force": True},
    )
    assert resp.status_code == 404

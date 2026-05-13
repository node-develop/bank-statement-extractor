"""Tests for POST /extract and health probes.

All tests use ``starlette.testclient.TestClient`` (ships with FastAPI).
The LangGraph graph is mocked at the ``build_graph`` / ``build_checkpointer``
level so no real Anthropic calls are made in CI.

Etalon reference: docs/ixonia-etalon.md, period #1 (Apr 2025, account 1664).
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from src.models import (
    Account,
    ExtractResult,
    Period,
    PeriodResult,
    Reconciliation,
    Summary,
)

# ---------------------------------------------------------------------------
# Etalon fixture builder
# ---------------------------------------------------------------------------


def _etalon_result() -> ExtractResult:
    """Build an ExtractResult matching Ixonia Apr 2025 etalon numbers."""
    account = Account(
        chunk_id="period_01",
        bank="Ixonia Bank",
        account_last4="1664",
        period=Period(start=date(2025, 4, 1), end=date(2025, 4, 30)),
    )
    summary = Summary(
        chunk_id="period_01",
        beginning_balance=Decimal("597068.70"),
        ending_balance=Decimal("509121.59"),
        deposits_total=Decimal("1214254.05"),
        deposits_count=81,
        withdrawals_total=Decimal("1302201.16"),
        withdrawals_count=111,
    )
    reconciliation = Reconciliation(
        chunk_id="period_01",
        reconciled=True,
        delta=Decimal("0.00"),
        notes=[],
    )
    period_result = PeriodResult(
        chunk_id="period_01",
        account=account,
        summary=summary,
        transactions=[],
        layout="ixonia_business_basic",
        reconciliation=reconciliation,
    )
    return ExtractResult(
        periods=[period_result],
        statement_sha256="a" * 64,
        langsmith_run_url=None,
        errors=[],
    )


# ---------------------------------------------------------------------------
# Shared fixture: app with mocked graph + checkpointer
# ---------------------------------------------------------------------------


@pytest.fixture()
def client_with_mock_graph(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Return (TestClient, mock_graph) with all external deps patched."""
    import src.api.main as api_main

    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(return_value={"final": _etalon_result()})

    monkeypatch.setattr(
        "src.api.main.build_graph",
        lambda checkpointer=None: fake_graph,
    )

    async def _fake_async_checkpointer() -> tuple[MagicMock, Any]:
        async def _noop() -> None:
            return None

        return MagicMock(), _noop

    monkeypatch.setattr(
        "src.api.main.build_async_checkpointer",
        _fake_async_checkpointer,
    )

    app = api_main.create_app()
    with TestClient(app) as client:
        yield client, fake_graph


# ---------------------------------------------------------------------------
# Minimal stub PDF bytes (valid-enough header to pass content-type check)
# ---------------------------------------------------------------------------

_STUB_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


# ---------------------------------------------------------------------------
# Test 1: happy path — 200, etalon numbers present in response
# ---------------------------------------------------------------------------


def test_extract_happy_path(client_with_mock_graph: Any) -> None:
    client, fake_graph = client_with_mock_graph
    response = client.post(
        "/extract",
        files={"file": ("statement.pdf", io.BytesIO(_STUB_PDF), "application/pdf")},
    )
    assert response.status_code == 200
    body = response.json()

    assert len(body["periods"]) == 1
    period = body["periods"][0]
    assert period["summary"]["deposits_count"] == 81
    assert period["summary"]["withdrawals_count"] == 111
    assert period["reconciliation"]["reconciled"] is True

    # Decimal fields must be serialized as quoted strings, not bare floats
    assert period["summary"]["beginning_balance"] == "597068.70"
    assert period["summary"]["ending_balance"] == "509121.59"
    assert period["summary"]["deposits_total"] == "1214254.05"
    assert period["summary"]["withdrawals_total"] == "1302201.16"

    # sha256 must equal the digest of the actual uploaded bytes — this is
    # the cache / dedup key that LangSmith uses to find re-runs.  Compute
    # the expected digest directly from _STUB_PDF and assert the endpoint
    # both forwarded it to the graph config and surfaced it on the response.
    import hashlib

    expected_sha = hashlib.sha256(_STUB_PDF).hexdigest()
    call_kwargs = fake_graph.ainvoke.call_args.kwargs
    assert call_kwargs["config"]["metadata"]["statement_hash"] == expected_sha, (
        "endpoint must pass the real sha256 to LangSmith metadata"
    )
    # statement_sha256 on ExtractResult is populated by the graph from
    # RawStatement.sha256 (M0) — in the mock fixture this is "a"*64.
    # Assert the wire shape (64-hex) rather than the value (mock-specific).
    sha = body["statement_sha256"]
    assert len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)


# ---------------------------------------------------------------------------
# Test 2: reject non-PDF content-type → 415
# ---------------------------------------------------------------------------


def test_extract_rejects_non_pdf(client_with_mock_graph: Any) -> None:
    client, _ = client_with_mock_graph
    response = client.post(
        "/extract",
        files={"file": ("data.bin", io.BytesIO(b"\x00\x01\x02"), "application/octet-stream")},
    )
    assert response.status_code == 415


# ---------------------------------------------------------------------------
# Test 3: reject oversized upload → 413
# ---------------------------------------------------------------------------


def test_extract_rejects_oversize(client_with_mock_graph: Any) -> None:
    client, _ = client_with_mock_graph
    big = b"A" * (26 * 1024 * 1024)  # 26 MB > 25 MB limit
    response = client.post(
        "/extract",
        files={"file": ("big.pdf", io.BytesIO(big), "application/pdf")},
    )
    assert response.status_code == 413


# ---------------------------------------------------------------------------
# Test 4: OCR text companion — graph receives txt_path
# ---------------------------------------------------------------------------


def test_extract_ocr_text_companion(client_with_mock_graph: Any) -> None:
    client, fake_graph = client_with_mock_graph
    response = client.post(
        "/extract",
        files={
            "file": ("statement.pdf", io.BytesIO(_STUB_PDF), "application/pdf"),
            "ocr_text": ("statement.txt", io.BytesIO(b"some ocr text"), "text/plain"),
        },
    )
    assert response.status_code == 200

    # Verify graph was called with a non-None txt_path
    call_args = fake_graph.ainvoke.call_args
    initial_state: dict[str, Any] = call_args[0][0]
    assert initial_state["txt_path"] is not None
    assert isinstance(initial_state["txt_path"], str)
    assert initial_state["txt_path"].endswith(".txt")


# ---------------------------------------------------------------------------
# Test 5: PDF unreadable → 422
# ---------------------------------------------------------------------------


def test_extract_pdf_unreadable_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.api.main as api_main

    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock(
        side_effect=RuntimeError("ingest: PDF unreadable — pdfplumber and pypdf both failed")
    )

    monkeypatch.setattr(
        "src.api.main.build_graph",
        lambda checkpointer=None: fake_graph,
    )

    async def _fake_async_checkpointer() -> tuple[MagicMock, Any]:
        async def _noop() -> None:
            return None

        return MagicMock(), _noop

    monkeypatch.setattr(
        "src.api.main.build_async_checkpointer",
        _fake_async_checkpointer,
    )

    app = api_main.create_app()
    with TestClient(app) as client:
        response = client.post(
            "/extract",
            files={"file": ("bad.pdf", io.BytesIO(_STUB_PDF), "application/pdf")},
        )
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "pdf_unreadable"


# ---------------------------------------------------------------------------
# Test 6: /healthz always 200
# ---------------------------------------------------------------------------


def test_healthz_returns_200(client_with_mock_graph: Any) -> None:
    client, _ = client_with_mock_graph
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Test 7: /readyz → 503 without ANTHROPIC_API_KEY
# ---------------------------------------------------------------------------


def test_readyz_returns_503_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.api.main as api_main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(
        "src.api.main.build_graph",
        lambda checkpointer=None: MagicMock(),
    )

    async def _fake_async_checkpointer() -> tuple[MagicMock, Any]:
        async def _noop() -> None:
            return None

        return MagicMock(), _noop

    monkeypatch.setattr(
        "src.api.main.build_async_checkpointer",
        _fake_async_checkpointer,
    )

    app = api_main.create_app()
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert "ANTHROPIC_API_KEY" in body["reason"]


# ---------------------------------------------------------------------------
# Test 8: /readyz → 200 with key set
# ---------------------------------------------------------------------------


def test_readyz_returns_200_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.api.main as api_main

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(
        "src.api.main.build_graph",
        lambda checkpointer=None: MagicMock(),
    )

    async def _fake_async_checkpointer() -> tuple[MagicMock, Any]:
        async def _noop() -> None:
            return None

        return MagicMock(), _noop

    monkeypatch.setattr(
        "src.api.main.build_async_checkpointer",
        _fake_async_checkpointer,
    )

    app = api_main.create_app()
    with TestClient(app) as client:
        response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"

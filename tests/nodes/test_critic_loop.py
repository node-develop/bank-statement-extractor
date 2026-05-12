"""Unit tests for src/nodes/critic_loop.py — business-intent assertions (rule 9).

All tests monkeypatch ``_get_llm`` so no real Anthropic API key is needed.

Test matrix
-----------
1. test_critic_emits_hint_on_failure         — LLM returns valid hint; assert hint in errors[].
2. test_critic_skips_when_all_reconciled     — no failures; retry_count unchanged.
3. test_critic_error_path_bumps_retry_count  — LLM raises ValueError; retry_count still bumped.
4. test_should_run_critic_returns_finalize_when_retry_count_geq_2
5. test_should_run_critic_returns_critic_on_failure_low_retry
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

from src.models import (
    PeriodChunk,
    Reconciliation,
    Summary,
    Transaction,
)
from src.nodes.critic_loop import CriticHint, critic, should_run_critic

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chunk(chunk_id: str = "period_01") -> PeriodChunk:
    return PeriodChunk(
        chunk_id=chunk_id,
        page_range=(1, 2),
        pdf_text="",
        ocr_slice=None,
        account_hint_last4="1664",
    )


def _make_reconciliation(chunk_id: str, reconciled: bool) -> Reconciliation:
    return Reconciliation(
        chunk_id=chunk_id,
        reconciled=reconciled,
        delta=Decimal("0.00") if reconciled else Decimal("1809.28"),
        notes=[] if reconciled else ["deposits_count: actual=80 vs summary=81"],
    )


def _make_summary(chunk_id: str = "period_01") -> Summary:
    return Summary(
        chunk_id=chunk_id,
        beginning_balance=Decimal("597068.70"),
        ending_balance=Decimal("509121.59"),
        deposits_total=Decimal("1214254.05"),
        deposits_count=81,
        withdrawals_total=Decimal("1302201.16"),
        withdrawals_count=111,
    )


def _make_transaction(chunk_id: str = "period_01", direction: str = "credit") -> Transaction:
    return Transaction(
        chunk_id=chunk_id,
        date=date(2025, 4, 1),
        description="TEST PAYMENT",
        amount=Decimal("100.00"),
        direction=direction,  # type: ignore[arg-type]
        running_balance=None,
    )


def _make_hint(
    chunk_id: str = "period_01",
    extractor: str = "extract_transactions",
    hint_text: str = "Re-check the running balance delta on row 3.",
) -> CriticHint:
    return CriticHint(chunk_id=chunk_id, extractor=extractor, hint=hint_text)  # type: ignore[arg-type]


def _mock_llm_returning(hint: CriticHint) -> MagicMock:
    """Return a mock that behaves like _get_llm().with_structured_output(CriticHint)."""
    structured = MagicMock()
    structured.invoke.return_value = hint
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


# ---------------------------------------------------------------------------
# GraphState helpers
# ---------------------------------------------------------------------------


def _make_state(
    reconciliations: list[Reconciliation],
    retry_count: int = 0,
    summaries: list[Summary] | None = None,
    transactions: list[Transaction] | None = None,
    period_chunks: list[PeriodChunk] | None = None,
) -> Any:
    """Build a minimal dict that satisfies the GraphState fields used by critic."""
    return {
        "pdf_path": "/tmp/test.pdf",
        "txt_path": None,
        "period_chunks": period_chunks or [_make_chunk()],
        "layouts": [],
        "accounts": [],
        "summaries": summaries or [_make_summary()],
        "transactions": transactions or [],
        "reconciliations": reconciliations,
        "retry_count": retry_count,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Tests for ``critic`` node
# ---------------------------------------------------------------------------


class TestCriticNode:
    def test_critic_emits_hint_on_failure(self) -> None:
        """When there is an un-reconciled period, critic emits a hint in errors[]."""
        hint = _make_hint()
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=False)],
            summaries=[_make_summary()],
            transactions=[_make_transaction()],
        )

        with patch("src.nodes.critic_loop._get_llm", return_value=_mock_llm_returning(hint)):
            result = critic(state)

        assert result["retry_count"] == 1
        assert len(result["errors"]) == 1
        error_str = result["errors"][0]
        assert "critic suggested:" in error_str
        assert "extract_transactions" in error_str
        assert "period_01" in error_str
        # pending_hint must be set
        assert "pending_hint" in result
        assert isinstance(result["pending_hint"], CriticHint)
        assert result["pending_hint"].extractor == "extract_transactions"

    def test_critic_skips_when_all_reconciled(self) -> None:
        """When all reconciliations pass, critic returns without bumping retry_count."""
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=True)],
            retry_count=0,
        )

        # _get_llm should never be called
        with patch("src.nodes.critic_loop._get_llm") as mock_get_llm:
            result = critic(state)
            mock_get_llm.assert_not_called()

        # retry_count must NOT appear in result (no increment)
        assert "retry_count" not in result
        assert result["errors"] == ["critic invoked but all periods reconciled"]

    def test_critic_error_path_bumps_retry_count(self) -> None:
        """When the LLM raises ValueError, retry_count is still incremented."""
        llm_mock = MagicMock()
        structured = MagicMock()
        structured.invoke.side_effect = ValueError("simulated LLM parse error")
        llm_mock.with_structured_output.return_value = structured

        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=False)],
            retry_count=0,
        )

        with patch("src.nodes.critic_loop._get_llm", return_value=llm_mock):
            result = critic(state)

        assert result["retry_count"] == 1
        assert len(result["errors"]) == 1
        assert "critic: failed to produce hint" in result["errors"][0]
        # No pending_hint on error path
        assert "pending_hint" not in result

    def test_critic_targets_first_failed_chunk(self) -> None:
        """When multiple chunks fail, critic targets the first failing one."""
        hint = _make_hint(chunk_id="period_01")
        state = _make_state(
            reconciliations=[
                _make_reconciliation("period_01", reconciled=False),
                _make_reconciliation("period_02", reconciled=False),
            ],
            summaries=[_make_summary("period_01"), _make_summary("period_02")],
            retry_count=0,
        )

        with patch("src.nodes.critic_loop._get_llm", return_value=_mock_llm_returning(hint)):
            result = critic(state)

        # Should target period_01 (first failure)
        assert result["pending_hint"].chunk_id == "period_01"

    def test_critic_chunk_id_overrides_llm_echo(self) -> None:
        """chunk_id in CriticHint is always taken from the failure, not the LLM."""
        # LLM returns a hint with a wrong chunk_id (simulates LLM hallucination)
        wrong_hint = _make_hint(chunk_id="wrong_id")
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=False)],
        )

        with patch("src.nodes.critic_loop._get_llm", return_value=_mock_llm_returning(wrong_hint)):
            result = critic(state)

        # chunk_id must be corrected to "period_01"
        assert result["pending_hint"].chunk_id == "period_01"


# ---------------------------------------------------------------------------
# Tests for ``should_run_critic`` router
# ---------------------------------------------------------------------------


class TestShouldRunCritic:
    def test_returns_critic_on_failure_low_retry(self) -> None:
        """Routes to critic when there is a failure and retry_count == 0."""
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=False)],
            retry_count=0,
        )
        assert should_run_critic(state) == "critic"

    def test_returns_critic_when_retry_count_is_1(self) -> None:
        """Routes to critic when retry_count == 1 (still below cap of 2)."""
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=False)],
            retry_count=1,
        )
        assert should_run_critic(state) == "critic"

    def test_returns_finalize_when_retry_count_geq_2(self) -> None:
        """Routes to finalize when retry_count == 2 even if failures exist."""
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=False)],
            retry_count=2,
        )
        assert should_run_critic(state) == "finalize"

    def test_returns_finalize_when_retry_count_exceeds_cap(self) -> None:
        """Routes to finalize when retry_count > 2 (defensive)."""
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=False)],
            retry_count=5,
        )
        assert should_run_critic(state) == "finalize"

    def test_returns_finalize_when_all_reconciled(self) -> None:
        """Routes to finalize when all periods are reconciled."""
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=True)],
            retry_count=0,
        )
        assert should_run_critic(state) == "finalize"

    def test_returns_finalize_when_no_reconciliations(self) -> None:
        """Routes to finalize when reconciliations list is empty (defensive)."""
        state = _make_state(reconciliations=[], retry_count=0)
        assert should_run_critic(state) == "finalize"

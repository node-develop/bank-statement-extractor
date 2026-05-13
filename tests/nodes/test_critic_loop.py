"""Unit tests for src/nodes/critic_loop.py — business-intent assertions.

``critic`` consumes ``verifier_reports`` (not ``reconciliations``); the
deprecated ``should_run_critic`` retains its old contract and is exercised
separately for backward compat.

All tests monkeypatch ``_get_llm`` so no real Anthropic API key is needed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

from src.models import (
    Gap,
    PeriodChunk,
    Reconciliation,
    Summary,
    Suspect,
    Transaction,
    VerifierReport,
)
from src.nodes.critic_loop import (
    CriticHint,
    critic,
    route_after_verifier,
    should_run_critic,
)

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


def _make_verifier_report(
    chunk_id: str = "period_01",
    n_suspects: int = 1,
) -> VerifierReport:
    suspects = [
        Suspect(
            chunk_id=chunk_id,
            row_index=i,
            code="balance_chain_break",  # type: ignore[arg-type]
            reason=f"row {i} broken",
        )
        for i in range(n_suspects)
    ]
    return VerifierReport(
        chunk_id=chunk_id,
        confidence=Decimal("0.50"),
        suspects=suspects,
        gaps=[]
        if n_suspects == 0
        else [
            Gap(
                chunk_id=chunk_id,
                after_row_index=0,
                date_range=(date(2025, 4, 1), date(2025, 4, 2)),
                missing_amount=Decimal("50.00"),
            )
        ],
    )


def _mock_llm_returning(hint: CriticHint) -> MagicMock:
    """Return a mock that behaves like _get_llm().with_structured_output(CriticHint).

    The defensive fallback in ``critic_loop._invoke_critic_llm`` accepts either
    the parsed hint OR an include_raw dict; here we return the hint directly.
    """
    structured = MagicMock()
    structured.invoke.return_value = hint
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    llm.model = "claude-haiku-4-5"
    return llm


# ---------------------------------------------------------------------------
# GraphState helper — takes verifier_reports
# ---------------------------------------------------------------------------


def _make_state(
    verifier_reports: list[VerifierReport] | None = None,
    reconciliations: list[Reconciliation] | None = None,
    retry_count: int = 0,
    summaries: list[Summary] | None = None,
    transactions: list[Transaction] | None = None,
    period_chunks: list[PeriodChunk] | None = None,
    cumulative_cost_usd: Decimal | None = None,
) -> Any:
    """Build a minimal dict that satisfies the GraphState fields used by critic."""
    out: dict[str, Any] = {
        "pdf_path": "/tmp/test.pdf",
        "txt_path": None,
        "period_chunks": period_chunks or [_make_chunk()],
        "layouts": [],
        "accounts": [],
        "summaries": summaries or [_make_summary()],
        "transactions": transactions or [],
        "reconciliations": reconciliations or [],
        "verifier_reports": verifier_reports or [],
        "retry_count": retry_count,
        "errors": [],
    }
    if cumulative_cost_usd is not None:
        out["cumulative_cost_usd"] = cumulative_cost_usd
    return out


# ---------------------------------------------------------------------------
# Tests for ``critic`` node
# ---------------------------------------------------------------------------


class TestCriticNode:
    def test_critic_emits_hint_on_failure(self) -> None:
        """When verifier_reports has suspects, critic emits a hint in notes[].

        The hint is informational (which extractor to retry + why), not an
        error. It belongs in notes[] so the frontend can show it in a
        non-alarming info block alongside other pipeline notices.
        """
        hint = _make_hint()
        state = _make_state(
            verifier_reports=[_make_verifier_report("period_01", n_suspects=2)],
            summaries=[_make_summary()],
            transactions=[_make_transaction()],
        )

        with patch("src.nodes.critic_loop._get_llm", return_value=_mock_llm_returning(hint)):
            result = critic(state)

        assert result["retry_count"] == 1
        assert "errors" not in result, "Critic success path must not write to errors[]"
        assert len(result["notes"]) == 1
        note_str = result["notes"][0]
        assert "Critic re-ran" in note_str
        assert "extract_transactions" in note_str
        assert "period_01" in note_str
        assert "pending_hint" in result
        assert isinstance(result["pending_hint"], CriticHint)
        assert result["pending_hint"].extractor == "extract_transactions"

    def test_critic_skips_when_no_suspects(self) -> None:
        """When all verifier reports are clean, critic returns without bumping."""
        state = _make_state(
            verifier_reports=[_make_verifier_report("period_01", n_suspects=0)],
            retry_count=0,
        )

        with patch("src.nodes.critic_loop._get_llm") as mock_get_llm:
            result = critic(state)
            mock_get_llm.assert_not_called()

        assert "retry_count" not in result
        assert result["errors"] == ["critic invoked but no verifier suspects"]

    def test_critic_error_path_bumps_retry_count(self) -> None:
        """When the LLM raises ValueError, retry_count is still incremented."""
        llm_mock = MagicMock()
        structured = MagicMock()
        structured.invoke.side_effect = ValueError("simulated LLM parse error")
        llm_mock.with_structured_output.return_value = structured
        llm_mock.model = "claude-haiku-4-5"

        state = _make_state(
            verifier_reports=[_make_verifier_report("period_01", n_suspects=1)],
            retry_count=0,
        )

        with patch("src.nodes.critic_loop._get_llm", return_value=llm_mock):
            result = critic(state)

        assert result["retry_count"] == 1
        assert len(result["errors"]) == 1
        assert "critic: failed to produce hint" in result["errors"][0]
        assert "pending_hint" not in result

    def test_critic_targets_first_failed_chunk(self) -> None:
        """When multiple chunks have suspects, critic targets the first."""
        hint = _make_hint(chunk_id="period_01")
        state = _make_state(
            verifier_reports=[
                _make_verifier_report("period_01", n_suspects=1),
                _make_verifier_report("period_02", n_suspects=2),
            ],
            summaries=[_make_summary("period_01"), _make_summary("period_02")],
            retry_count=0,
        )

        with patch("src.nodes.critic_loop._get_llm", return_value=_mock_llm_returning(hint)):
            result = critic(state)

        assert result["pending_hint"].chunk_id == "period_01"

    def test_critic_chunk_id_overrides_llm_echo(self) -> None:
        """chunk_id in CriticHint is always taken from the suspect chunk, not the LLM."""
        wrong_hint = _make_hint(chunk_id="wrong_id")
        state = _make_state(
            verifier_reports=[_make_verifier_report("period_01", n_suspects=1)],
        )

        with patch("src.nodes.critic_loop._get_llm", return_value=_mock_llm_returning(wrong_hint)):
            result = critic(state)

        assert result["pending_hint"].chunk_id == "period_01"


# ---------------------------------------------------------------------------
# Tests for ``route_after_verifier`` router
# ---------------------------------------------------------------------------


class TestRouteAfterVerifier:
    def test_routes_to_reconcile_when_clean(self) -> None:
        """No suspects, no cost cap → reconcile."""
        state = _make_state(
            verifier_reports=[_make_verifier_report("period_01", n_suspects=0)],
            cumulative_cost_usd=Decimal("0"),
        )
        assert route_after_verifier(state) == "reconcile"

    def test_routes_to_critic_on_few_suspects(self) -> None:
        """1-3 suspects + retries left → critic."""
        state = _make_state(
            verifier_reports=[_make_verifier_report("period_01", n_suspects=2)],
            retry_count=0,
            cumulative_cost_usd=Decimal("0"),
        )
        assert route_after_verifier(state) == "critic"

    def test_routes_to_await_review_on_many_suspects(self) -> None:
        """>3 suspects → await_review."""
        state = _make_state(
            verifier_reports=[_make_verifier_report("period_01", n_suspects=5)],
            retry_count=0,
            cumulative_cost_usd=Decimal("0"),
        )
        assert route_after_verifier(state) == "await_review"

    def test_routes_to_await_review_on_retry_exhausted(self) -> None:
        """retry_count >= 2 → await_review even with few suspects."""
        state = _make_state(
            verifier_reports=[_make_verifier_report("period_01", n_suspects=1)],
            retry_count=2,
            cumulative_cost_usd=Decimal("0"),
        )
        assert route_after_verifier(state) == "await_review"

    def test_routes_to_await_review_on_cost_cap(self, monkeypatch) -> None:
        """cumulative_cost_usd >= cap → await_review."""
        # Reload pricing module so HARD_COST_CAP_USD picks up the env override.
        import importlib

        import src.api.pricing as pricing_mod

        monkeypatch.setenv("BSA_COST_CAP_USD", "0.01")
        importlib.reload(pricing_mod)
        # Also reload critic_loop so the late-bound import inside
        # route_after_verifier sees the new HARD_COST_CAP_USD value.
        import src.nodes.critic_loop as critic_mod

        importlib.reload(critic_mod)
        try:
            state = _make_state(
                verifier_reports=[_make_verifier_report("period_01", n_suspects=0)],
                cumulative_cost_usd=Decimal("0.05"),
            )
            assert critic_mod.route_after_verifier(state) == "await_review"
        finally:
            # Reset for other tests.
            monkeypatch.delenv("BSA_COST_CAP_USD", raising=False)
            importlib.reload(pricing_mod)
            importlib.reload(critic_mod)


# ---------------------------------------------------------------------------
# Tests for the DEPRECATED ``should_run_critic`` router (kept for back-compat)
# ---------------------------------------------------------------------------


class TestShouldRunCritic:
    def test_returns_critic_on_failure_low_retry(self) -> None:
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=False)],
            retry_count=0,
        )
        assert should_run_critic(state) == "critic"

    def test_returns_critic_when_retry_count_is_1(self) -> None:
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=False)],
            retry_count=1,
        )
        assert should_run_critic(state) == "critic"

    def test_returns_finalize_when_retry_count_geq_2(self) -> None:
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=False)],
            retry_count=2,
        )
        assert should_run_critic(state) == "finalize"

    def test_returns_finalize_when_all_reconciled(self) -> None:
        state = _make_state(
            reconciliations=[_make_reconciliation("period_01", reconciled=True)],
            retry_count=0,
        )
        assert should_run_critic(state) == "finalize"

    def test_returns_finalize_when_no_reconciliations(self) -> None:
        state = _make_state(reconciliations=[], retry_count=0)
        assert should_run_critic(state) == "finalize"

"""End-to-end graph tests with mocked LLM nodes.

All LLM singletons are monkeypatched so no real Anthropic API key is required.
The graph is invoked via ``build_graph().invoke()``; the checkpointer is the
in-memory saver (``LANGGRAPH_CHECKPOINTER=memory``).

Test matrix
-----------
1. test_e2e_single_period_reconciles
   - Build a RawStatement from the Apr-2025 chunk of the Ixonia OCR text.
   - Mock all four LLM _get_llm functions to return Ixonia Apr-2025 etalon.
   - Mock ingest to return the pre-built RawStatement.
   - Assert state["final"] is an ExtractResult with one reconciled period.
   - Assert beginning_balance == Decimal("597068.70").

2. test_e2e_critic_runs_on_failure
   - Mock extractors to produce a mismatched summary (wrong deposits_count).
   - Assert critic was invoked: errors[] contains an entry with "critic suggested:".
   - Assert reconciled=False for the period.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.models import (
    Account,
    ExtractResult,
    LayoutLabel,
    Period,
    RawStatement,
    Summary,
    Transaction,
)

# ---------------------------------------------------------------------------
# Path to the Ixonia OCR fixture (read-only, Task/)
# ---------------------------------------------------------------------------
_OCR_PATH = Path("/Users/izual/PycharmProjects/bank-statement-analizer/Task/ixonia_binder2_ocr.txt")

# ---------------------------------------------------------------------------
# Etalon values for Apr 2025 (docs/ixonia-etalon.md, period #1)
# ---------------------------------------------------------------------------
_APR_CHUNK_ID = "period_01"
_APR_BEGINNING = Decimal("597068.70")
_APR_ENDING = Decimal("509121.59")
_APR_DEP_TOTAL = Decimal("1214254.05")
_APR_DEP_COUNT = 81
_APR_WD_TOTAL = Decimal("1302201.16")
_APR_WD_COUNT = 111


# ---------------------------------------------------------------------------
# Helpers to build test fixtures
# ---------------------------------------------------------------------------


def _load_apr_ocr_slice() -> str:
    """Return the Apr-2025 OCR slice (lines 38..1132 inclusive, 1-based)."""
    if not _OCR_PATH.exists():
        pytest.skip(f"Ixonia OCR fixture not found at {_OCR_PATH}")
    lines = _OCR_PATH.read_text(encoding="utf-8").splitlines()
    # architecture.md: chunk 1 begins at line 38 (1-based), chunk 2 at 1133.
    return "\n".join(lines[37:1132])  # 0-based slice [37, 1132)


def _make_raw_from_slice(ocr_slice: str) -> RawStatement:
    return RawStatement(
        pages=[ocr_slice],
        ocr_text=ocr_slice,
        sha256="a" * 64,
        page_count=1,
    )


def _make_apr_account() -> Account:
    return Account(
        chunk_id=_APR_CHUNK_ID,
        bank="Ixonia Bank",
        account_last4="1664",
        period=Period(start=date(2025, 4, 1), end=date(2025, 4, 30)),
    )


def _make_apr_summary() -> Summary:
    return Summary(
        chunk_id=_APR_CHUNK_ID,
        beginning_balance=_APR_BEGINNING,
        ending_balance=_APR_ENDING,
        deposits_total=_APR_DEP_TOTAL,
        deposits_count=_APR_DEP_COUNT,
        withdrawals_total=_APR_WD_TOTAL,
        withdrawals_count=_APR_WD_COUNT,
    )


def _make_apr_layout() -> LayoutLabel:
    return LayoutLabel(chunk_id=_APR_CHUNK_ID, label="ixonia_business_basic")


def _make_apr_transactions() -> list[Transaction]:
    """Build exactly 81 credits and 111 debits that sum to the etalon totals.

    We use exact per-transaction amounts to make reconciliation pass precisely.
    Credit: 81 x 14991.41 = 1,214,304.21 - too high. Use exact split instead.

    Strategy: 80 credits of 15178.17 + 1 credit of 0.69 = 1,214,254.05
              110 debits of 11838.19 + 1 debit of 0.06 = 1,302,201.16
    Actually let's just use the totals directly via one large tx + remainder.
    Simpler: sum must equal totals within EPSILON. Build N-1 uniform txs and
    one remainder tx.
    """
    credits: list[Transaction] = []
    per_credit = Decimal("14991.41")
    for i in range(_APR_DEP_COUNT - 1):
        credits.append(
            Transaction(
                chunk_id=_APR_CHUNK_ID,
                date=date(2025, 4, 1),
                description=f"CREDIT {i}",
                amount=per_credit,
                direction="credit",
                running_balance=None,
            )
        )
    remainder_credit = _APR_DEP_TOTAL - per_credit * (_APR_DEP_COUNT - 1)
    credits.append(
        Transaction(
            chunk_id=_APR_CHUNK_ID,
            date=date(2025, 4, 1),
            description="CREDIT remainder",
            amount=remainder_credit,
            direction="credit",
            running_balance=None,
        )
    )

    debits: list[Transaction] = []
    per_debit = Decimal("11731.54")
    for i in range(_APR_WD_COUNT - 1):
        debits.append(
            Transaction(
                chunk_id=_APR_CHUNK_ID,
                date=date(2025, 4, 1),
                description=f"DEBIT {i}",
                amount=per_debit,
                direction="debit",
                running_balance=None,
            )
        )
    remainder_debit = _APR_WD_TOTAL - per_debit * (_APR_WD_COUNT - 1)
    debits.append(
        Transaction(
            chunk_id=_APR_CHUNK_ID,
            date=date(2025, 4, 1),
            description="DEBIT remainder",
            amount=remainder_debit,
            direction="debit",
            running_balance=None,
        )
    )

    return credits + debits


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _llm_for_layout(label: LayoutLabel) -> MagicMock:
    structured = MagicMock()
    structured.invoke.return_value = label
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def _llm_for_account(account: Account) -> MagicMock:
    structured = MagicMock()
    structured.invoke.return_value = account
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def _llm_for_summary(summary: Summary) -> MagicMock:
    structured = MagicMock()
    structured.invoke.return_value = summary
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


def _llm_for_transactions(txs: list[Transaction]) -> MagicMock:
    """Mock for extract_transactions, which uses a _TransactionList wrapper."""
    tx_list_mock = MagicMock()
    tx_list_mock.transactions = txs
    structured = MagicMock()
    structured.invoke.return_value = tx_list_mock
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm


# ---------------------------------------------------------------------------
# Test 1 — single period, full graph, happy path
# ---------------------------------------------------------------------------


class TestE2ESinglePeriodReconciles:
    """Invoke the full graph with one mocked period; assert reconciliation passes."""

    def test_e2e_single_period_reconciles(self) -> None:
        ocr_slice = _load_apr_ocr_slice()
        raw = _make_raw_from_slice(ocr_slice)

        layout = _make_apr_layout()
        account = _make_apr_account()
        summary = _make_apr_summary()
        transactions = _make_apr_transactions()

        # Patch ingest to return the pre-built RawStatement (skip PDF I/O)
        def _fake_ingest(state: Any) -> dict[str, Any]:
            return {"raw": raw, "errors": []}

        from src.graph.builder import build_graph

        # builder.py imports node functions at module-level with `from ... import fn`,
        # so the graph holds a direct reference to the local name in builder's namespace.
        # Patching src.graph.builder.ingest replaces that reference before graph.compile.
        with (
            patch("src.graph.builder.ingest", side_effect=_fake_ingest),
            patch("src.nodes.classify_layout._get_llm", return_value=_llm_for_layout(layout)),
            patch("src.nodes.extract_account._get_llm", return_value=_llm_for_account(account)),
            patch("src.nodes.extract_summary._get_llm", return_value=_llm_for_summary(summary)),
            patch(
                "src.nodes.extract_transactions._get_llm",
                return_value=_llm_for_transactions(transactions),
            ),
        ):
            # build_graph registers node functions at compile time;
            # the patches above are active before graph.compile() is called.
            graph = build_graph(checkpointer=None)
            initial: dict[str, Any] = {
                "pdf_path": "/tmp/fake.pdf",
                "txt_path": None,
                "layouts": [],
                "accounts": [],
                "summaries": [],
                "transactions": [],
                "reconciliations": [],
                "retry_count": 0,
                "errors": [],
            }
            config: dict[str, Any] = {
                "recursion_limit": 50,
            }
            result_state = graph.invoke(initial, config=config)

        assert "final" in result_state, "state['final'] must be set by finalize node"
        final: ExtractResult = result_state["final"]
        assert isinstance(final, ExtractResult)
        assert len(final.periods) == 1

        period = final.periods[0]
        assert period.chunk_id == _APR_CHUNK_ID
        assert period.reconciliation.reconciled is True, (
            f"Expected reconciled=True, got reconciled={period.reconciliation.reconciled} "
            f"notes={period.reconciliation.notes}"
        )
        assert period.summary.beginning_balance == _APR_BEGINNING
        assert period.summary.ending_balance == _APR_ENDING


# ---------------------------------------------------------------------------
# Test 2 — mismatched counts → critic runs
# ---------------------------------------------------------------------------


class TestE2ECriticRunsOnFailure:
    """When the extractor returns wrong counts, critic is invoked."""

    def test_e2e_critic_runs_on_failure(self) -> None:
        ocr_slice = _load_apr_ocr_slice()
        raw = _make_raw_from_slice(ocr_slice)

        layout = _make_apr_layout()
        account = _make_apr_account()
        # Summary claims 81 deposits but we'll only return 1 transaction total
        summary = _make_apr_summary()
        # Only 1 credit and 1 debit — count mismatch will fail reconcile
        bad_transactions = [
            Transaction(
                chunk_id=_APR_CHUNK_ID,
                date=date(2025, 4, 1),
                description="ONLY CREDIT",
                amount=Decimal("1214254.05"),
                direction="credit",
                running_balance=None,
            ),
            Transaction(
                chunk_id=_APR_CHUNK_ID,
                date=date(2025, 4, 1),
                description="ONLY DEBIT",
                amount=Decimal("1302201.16"),
                direction="debit",
                running_balance=None,
            ),
        ]

        # Critic LLM mock
        from src.nodes.critic_loop import CriticHint

        critic_hint = CriticHint(
            chunk_id=_APR_CHUNK_ID,
            extractor="extract_transactions",
            hint="Count mismatch: expected 81 deposits but got 1.",
        )
        critic_structured = MagicMock()
        critic_structured.invoke.return_value = critic_hint
        critic_llm = MagicMock()
        critic_llm.with_structured_output.return_value = critic_structured

        def _fake_ingest(state: Any) -> dict[str, Any]:
            return {"raw": raw, "errors": []}

        from src.graph.builder import build_graph

        with (
            patch("src.graph.builder.ingest", side_effect=_fake_ingest),
            patch("src.nodes.classify_layout._get_llm", return_value=_llm_for_layout(layout)),
            patch("src.nodes.extract_account._get_llm", return_value=_llm_for_account(account)),
            patch("src.nodes.extract_summary._get_llm", return_value=_llm_for_summary(summary)),
            patch(
                "src.nodes.extract_transactions._get_llm",
                return_value=_llm_for_transactions(bad_transactions),
            ),
            patch("src.nodes.critic_loop._get_llm", return_value=critic_llm),
        ):
            graph = build_graph(checkpointer=None)
            initial: dict[str, Any] = {
                "pdf_path": "/tmp/fake.pdf",
                "txt_path": None,
                "layouts": [],
                "accounts": [],
                "summaries": [],
                "transactions": [],
                "reconciliations": [],
                "retry_count": 0,
                "errors": [],
            }
            config: dict[str, Any] = {
                "recursion_limit": 50,
            }
            result_state = graph.invoke(initial, config=config)

        assert "final" in result_state
        final: ExtractResult = result_state["final"]

        # Period must be unreconciled (counts mismatch)
        period = final.periods[0]
        assert period.reconciliation.reconciled is False, (
            "Expected reconciled=False when transaction counts mismatch"
        )

        # Critic must have run — its hint appears in errors[]
        all_errors = final.errors
        critic_errors = [e for e in all_errors if "critic suggested:" in e]
        assert critic_errors, (
            f"Expected at least one 'critic suggested:' entry in errors[], got: {all_errors}"
        )

        # Structural invariant: reconciliations must NOT accumulate across
        # critic-loop retries.  The custom ``_reduce_by_chunk_id`` reducer in
        # state.py keeps the list at exactly one entry per chunk_id (rule 12).
        # split_periods produces the chunks; the count is the post-graph
        # ``period_chunks`` length, which matches ``final.periods``.
        n_chunks = len(result_state["period_chunks"])
        assert n_chunks >= 1, "expected at least one period_chunk produced"
        assert len(result_state["reconciliations"]) == n_chunks, (
            "reconciliations list duplicated across critic retries — "
            f"expected {n_chunks} entries (one per chunk_id), "
            f"got {len(result_state['reconciliations'])}"
        )
        assert len(final.periods) == n_chunks, (
            f"final.periods count mismatch: expected {n_chunks}, got {len(final.periods)}"
        )

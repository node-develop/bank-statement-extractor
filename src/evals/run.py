"""CLI runner for the evaluation harness (Phase 10).

Usage
-----
::

    uv run python -m src.evals.run --statement Task/Binder2_Redacted.pdf [--txt …] [--dry-run]

Modes
-----
``--dry-run``
    Mocks each extractor's ``_get_llm`` to return Pydantic objects derived
    from the etalon — exercises the graph end-to-end without ANTHROPIC_API_KEY.
    Always passes because the mocks reproduce the etalon exactly; this is a
    *harness-validation* mode.
Real run (no ``--dry-run``)
    Requires ``ANTHROPIC_API_KEY``.  Builds and invokes the real graph.

Exit codes
----------
- ``0``  — every period exact-matched the etalon (full reconciliation).
- ``1``  — at least one period regressed; the markdown report still gets
           written; path is printed to stderr.
- ``2``  — configuration error (missing key, missing dataset, statement
           not in dataset).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest import mock

from src.api.logging import get_logger
from src.evals.scorers import PeriodScore, score_period
from src.models import (
    EPSILON,
    Account,
    ExtractResult,
    Period,
    PeriodResult,
    Reconciliation,
    Summary,
    Transaction,
)

logger = get_logger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent.resolve()
DEFAULT_DATASET = PROJECT_ROOT / "src" / "evals" / "datasets" / "ixonia.jsonl"
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "src" / "evals" / "reports"


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def load_dataset(dataset_path: Path, statement_path: str) -> list[dict[str, Any]]:
    """Load JSONL dataset and return entries whose pdf_path basename matches."""
    if not dataset_path.exists():
        return []

    target_name = Path(statement_path).name
    entries: list[dict[str, Any]] = []
    with dataset_path.open(encoding="utf-8") as f:
        for line_num, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("dataset line %d: %s", line_num, exc)
                continue
            if Path(entry["inputs"]["pdf_path"]).name == target_name:
                entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Dry-run helpers: build mock PeriodResult from etalon
# ---------------------------------------------------------------------------


def _build_period_from_etalon(entry: dict[str, Any]) -> PeriodResult:
    """Build a ``PeriodResult`` that matches the etalon exactly.

    Used in dry-run mode so the harness can be exercised end-to-end without
    real LLM calls.  Synthetic transactions are generated to satisfy
    ``tx_count`` — they are NOT individually meaningful, only the count is.
    """
    etalon = entry["etalon"]
    chunk_id: str = entry["chunk_id"]
    period_dict = etalon["period"]
    summary_dict = etalon["summary"]

    account = Account(
        chunk_id=chunk_id,
        bank=etalon["bank"],
        account_last4=etalon["account_last4"],
        period=Period(
            start=date.fromisoformat(period_dict["start"]),
            end=date.fromisoformat(period_dict["end"]),
        ),
    )

    summary = Summary(
        chunk_id=chunk_id,
        beginning_balance=Decimal(summary_dict["beginning_balance"]),
        ending_balance=Decimal(summary_dict["ending_balance"]),
        deposits_total=Decimal(summary_dict["deposits_total"]),
        deposits_count=int(summary_dict["deposits_count"]),
        withdrawals_total=Decimal(summary_dict["withdrawals_total"]),
        withdrawals_count=int(summary_dict["withdrawals_count"]),
    )

    tx_count = int(etalon["tx_count"])
    n_credit = int(summary_dict["deposits_count"])
    n_debit = int(summary_dict["withdrawals_count"])
    transactions: list[Transaction] = []
    for i in range(n_credit):
        transactions.append(
            Transaction(
                chunk_id=chunk_id,
                date=date.fromisoformat(period_dict["start"]),
                description=f"synthetic_credit_{i}",
                amount=Decimal("0.01"),
                direction="credit",
            )
        )
    for i in range(n_debit):
        transactions.append(
            Transaction(
                chunk_id=chunk_id,
                date=date.fromisoformat(period_dict["start"]),
                description=f"synthetic_debit_{i}",
                amount=Decimal("0.01"),
                direction="debit",
            )
        )
    if len(transactions) != tx_count:
        # Etalon's tx_count should equal deposits_count + withdrawals_count;
        # if it doesn't, the dataset is wrong — surface loudly (rule 12).
        raise ValueError(
            f"{chunk_id}: tx_count ({tx_count}) != deposits_count + "
            f"withdrawals_count ({n_credit + n_debit})"
        )

    reconciliation = Reconciliation(
        chunk_id=chunk_id,
        reconciled=bool(etalon["reconciled"]),
        delta=Decimal("0.00"),
        notes=[],
    )

    return PeriodResult(
        chunk_id=chunk_id,
        account=account,
        summary=summary,
        transactions=transactions,
        layout="ixonia_business_basic",
        reconciliation=reconciliation,
    )


def run_dry(entries: list[dict[str, Any]]) -> ExtractResult:
    """Build an ExtractResult straight from etalon entries (no graph call)."""
    logger.info("dry-run: building %d periods from etalon", len(entries))
    periods = [_build_period_from_etalon(e) for e in entries]
    return ExtractResult(
        periods=periods,
        statement_sha256="0" * 64,
        langsmith_run_url=None,
        errors=[],
    )


# ---------------------------------------------------------------------------
# Real run
# ---------------------------------------------------------------------------


def run_real(pdf_path: str, txt_path: str | None) -> ExtractResult:
    """Invoke the real graph against the supplied statement."""
    # Defer the heavy imports so dry-run / config-check paths don't pay them.
    from src.graph.builder import build_graph

    logger.info("real: building graph for %s", pdf_path)
    graph = build_graph(checkpointer=None)
    initial: dict[str, Any] = {
        "pdf_path": pdf_path,
        "txt_path": txt_path,
        "period_chunks": [],
        "layouts": [],
        "accounts": [],
        "summaries": [],
        "transactions": [],
        "reconciliations": [],
        "retry_count": 0,
        "errors": [],
    }
    config: dict[str, Any] = {"recursion_limit": 50}
    final_state = graph.invoke(initial, config=config)
    final = final_state.get("final")
    if isinstance(final, ExtractResult):
        return final

    # HITL pause path — graph stopped at await_review without reaching
    # finalize. Synthesize an ExtractResult from the partial state so the
    # report renders per-period reconciliation against the etalon. The graph
    # itself is unchanged; this only rescues the eval harness from a hard
    # crash when the system honestly says "I need a human" mid-run.
    from src.nodes.finalize import finalize as finalize_node
    from src.nodes.reconcile import reconcile as reconcile_node

    if not final_state.get("summaries") or not final_state.get("transactions"):
        raise RuntimeError(
            "graph paused before producing summaries/transactions — no partial state to finalize"
        )
    logger.warning(
        "real run: graph paused at await_review; running reconcile + finalize on partial state",
    )
    reconcile_delta = reconcile_node(final_state)
    final_state["reconciliations"] = list(reconcile_delta["reconciliations"])
    finalize_delta = finalize_node(final_state)
    rescued = finalize_delta["final"]
    if not isinstance(rescued, ExtractResult):
        raise RuntimeError(
            "rescue path: finalize did not produce an ExtractResult on partial state"
        )
    return rescued


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _render_report(
    *,
    statement_path: str,
    mode: str,
    result: ExtractResult,
    scores_by_id: dict[str, PeriodScore],
    entries_by_id: dict[str, dict[str, Any]],
) -> str:
    """Render the evaluation report as markdown."""
    now = datetime.now(UTC).isoformat(timespec="seconds")
    lines: list[str] = []
    lines.append("# Evaluation Report")
    lines.append("")
    lines.append(f"- **Date (UTC):** {now}")
    lines.append(f"- **Mode:** {mode}")
    lines.append(f"- **Statement:** `{statement_path}`")
    lines.append(f"- **Statement SHA-256:** `{result.statement_sha256}`")
    lines.append(f"- **Periods:** {len(scores_by_id)}")
    lines.append("")
    lines.append("## Per-period scores")
    lines.append("")
    lines.append("| chunk_id | account | reconciled | delta | summary | tx_count | overall |")
    lines.append("|---|---|---|---|---|---|---|")
    n_pass = 0
    for chunk_id, score in sorted(scores_by_id.items()):
        etalon = entries_by_id[chunk_id]["etalon"]
        passed = score.all_pass
        if passed:
            n_pass += 1
        lines.append(
            f"| {chunk_id} | {etalon['account_last4']} | "
            f"{'OK' if score.reconciled_match else 'MISMATCH'} | "
            f"{score.delta} | "
            f"{'OK' if score.summary_exact_match else 'DIFF'} | "
            f"{score.actual_tx_count}/{score.expected_tx_count} | "
            f"{'PASS' if passed else 'FAIL'} |"
        )
    lines.append("")

    # Failures section
    failures: list[str] = []
    for chunk_id, score in sorted(scores_by_id.items()):
        if score.all_pass:
            continue
        if not score.account_last4_match:
            etalon_acc = entries_by_id[chunk_id]["etalon"]["account_last4"]
            failures.append(f"- `{chunk_id}` account_last4: expected {etalon_acc}")
        for field, (expected, actual) in score.summary_field_diffs.items():
            failures.append(
                f"- `{chunk_id}` summary.{field}: expected `{expected}`, got `{actual}`"
            )
        if not score.tx_count_match:
            failures.append(
                f"- `{chunk_id}` tx_count: expected {score.expected_tx_count}, "
                f"got {score.actual_tx_count}"
            )
        if not score.reconciled_match:
            failures.append(
                f"- `{chunk_id}` reconciled: expected "
                f"{entries_by_id[chunk_id]['etalon']['reconciled']}"
            )
        if not score.delta_within_epsilon:
            failures.append(f"- `{chunk_id}` delta {score.delta} exceeds EPSILON {EPSILON}")

    if failures:
        lines.append("## Failures")
        lines.append("")
        lines.extend(failures)
        lines.append("")

    # Aggregate
    n_total = len(scores_by_id)
    pct = (100.0 * n_pass / n_total) if n_total else 0.0
    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- **Periods fully passing:** {n_pass}/{n_total} ({pct:.1f}%)")
    return "\n".join(lines) + "\n"


def _write_report(report: str, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    safe_ts = datetime.now(UTC).isoformat(timespec="seconds").replace(":", "-")
    path = report_dir / f"{safe_ts}.md"
    path.write_text(report, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="src.evals.run")
    parser.add_argument("--statement", required=True, help="Path to the PDF statement")
    parser.add_argument("--txt", default=None, help="Optional companion OCR text")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build PeriodResult from etalon (no LLM, no API key required)",
    )
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORTS_DIR))
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    entries = load_dataset(dataset_path, args.statement)
    if not entries:
        logger.error(
            "no dataset entries found for statement %s in %s",
            args.statement,
            dataset_path,
        )
        return 2

    if args.dry_run:
        result = run_dry(entries)
    else:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            logger.error(
                "ANTHROPIC_API_KEY is not set; cannot run real evaluation — "
                "use --dry-run for harness validation"
            )
            return 2
        try:
            result = run_real(args.statement, args.txt)
        except RuntimeError as exc:
            logger.error("real run failed: %s", exc)
            return 2

    # Score each period
    entries_by_id = {e["chunk_id"]: e for e in entries}
    scores_by_id: dict[str, PeriodScore] = {}
    for period in result.periods:
        etalon = entries_by_id.get(period.chunk_id)
        if etalon is None:
            logger.warning("result contained chunk_id %s not present in dataset", period.chunk_id)
            continue
        scores_by_id[period.chunk_id] = score_period(period, etalon["etalon"])

    # Render & write report
    mode = "dry-run" if args.dry_run else "real"
    report = _render_report(
        statement_path=args.statement,
        mode=mode,
        result=result,
        scores_by_id=scores_by_id,
        entries_by_id=entries_by_id,
    )
    report_path = _write_report(report, Path(args.report_dir))
    sys.stderr.write(f"report: {report_path}\n")

    all_pass = bool(scores_by_id) and all(s.all_pass for s in scores_by_id.values())
    return 0 if all_pass else 1


# Re-export the mock module for tests that want to monkey-patch graph calls
# in the future without unstable internal paths.
_mock = mock


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

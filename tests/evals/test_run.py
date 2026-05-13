"""Tests for src/evals/run.py CLI — business intent."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

# The dataset already lives in the repo; tests reuse it.
_REPO = Path(__file__).resolve().parent.parent.parent
_DATASET = _REPO / "src" / "evals" / "datasets" / "ixonia.jsonl"
_STATEMENT = "Task/Binder2_Redacted.pdf"


def test_main_dry_run_returns_zero_and_writes_report(tmp_path: Path) -> None:
    from src.evals.run import main

    report_dir = tmp_path / "reports"
    exit_code = main(
        [
            "--statement",
            _STATEMENT,
            "--dry-run",
            "--dataset",
            str(_DATASET),
            "--report-dir",
            str(report_dir),
        ]
    )
    assert exit_code == 0, "dry-run should succeed end-to-end"
    reports = list(report_dir.glob("*.md"))
    assert len(reports) == 1, f"expected 1 report, found {reports}"
    body = reports[0].read_text(encoding="utf-8")
    # Business-intent assertions: every period reports a PASS line, and the
    # aggregate header records 10/10.
    assert "Periods fully passing:** 10/10" in body
    assert body.count("| PASS |") == 10


def test_main_real_mode_without_key_returns_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from src.evals.run import main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    exit_code = main(
        [
            "--statement",
            _STATEMENT,
            "--dataset",
            str(_DATASET),
            "--report-dir",
            str(tmp_path / "reports"),
        ]
    )
    assert exit_code == 2


def test_main_statement_not_in_dataset_returns_two(tmp_path: Path) -> None:
    from src.evals.run import main

    exit_code = main(
        [
            "--statement",
            "Task/does-not-exist.pdf",
            "--dry-run",
            "--dataset",
            str(_DATASET),
            "--report-dir",
            str(tmp_path / "reports"),
        ]
    )
    assert exit_code == 2


def test_main_returns_one_when_a_period_regresses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the runner produces a result that disagrees with the etalon,
    main() must exit 1 and the report must list the failure."""
    from datetime import date
    from decimal import Decimal

    from src.evals import run as run_mod
    from src.models import (
        Account,
        ExtractResult,
        Period,
        PeriodResult,
        Reconciliation,
        Summary,
    )

    def _wrong_result(entries: list[dict]) -> ExtractResult:
        # Build a result whose period_01 has the WRONG deposits_count
        # (80 instead of 81) — every other field is exact-match.
        chunk_id = "period_01"
        account = Account(
            chunk_id=chunk_id,
            bank="Ixonia Bank",
            account_last4="1664",
            period=Period(start=date(2025, 4, 1), end=date(2025, 4, 30)),
        )
        summary = Summary(
            chunk_id=chunk_id,
            beginning_balance=Decimal("597068.70"),
            ending_balance=Decimal("509121.59"),
            deposits_total=Decimal("1214254.05"),
            deposits_count=80,  # WRONG (etalon: 81)
            withdrawals_total=Decimal("1302201.16"),
            withdrawals_count=111,
        )
        period = PeriodResult(
            chunk_id=chunk_id,
            account=account,
            summary=summary,
            transactions=[],
            layout="ixonia_business_basic",
            reconciliation=Reconciliation(
                chunk_id=chunk_id, reconciled=True, delta=Decimal("0.00"), notes=[]
            ),
        )
        return ExtractResult(
            periods=[period],
            statement_sha256="0" * 64,
            langsmith_run_url=None,
            errors=[],
        )

    monkeypatch.setattr(run_mod, "run_dry", _wrong_result)

    report_dir = tmp_path / "reports"
    exit_code = run_mod.main(
        [
            "--statement",
            _STATEMENT,
            "--dry-run",
            "--dataset",
            str(_DATASET),
            "--report-dir",
            str(report_dir),
        ]
    )
    assert exit_code == 1, f"expected exit code 1 on regression, got {exit_code}"
    reports = list(report_dir.glob("*.md"))
    assert len(reports) == 1
    body = reports[0].read_text(encoding="utf-8")
    assert "## Failures" in body
    assert "deposits_count" in body

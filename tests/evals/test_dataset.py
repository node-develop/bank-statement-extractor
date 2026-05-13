"""Tests for src/evals/datasets/ixonia.jsonl (rule 9 — business intent)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_DATASET = (
    Path(__file__).resolve().parent.parent.parent / "src" / "evals" / "datasets" / "ixonia.jsonl"
)


@pytest.fixture
def entries() -> list[dict]:
    assert _DATASET.exists(), f"missing dataset: {_DATASET}"
    out: list[dict] = []
    with _DATASET.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def test_dataset_has_ten_entries(entries: list[dict]) -> None:
    assert len(entries) == 10


def test_dataset_chunk_ids_are_period_01_to_10(entries: list[dict]) -> None:
    expected = [f"period_{i:02d}" for i in range(1, 11)]
    assert [e["chunk_id"] for e in entries] == expected


def test_dataset_schema(entries: list[dict]) -> None:
    for e in entries:
        assert "chunk_id" in e
        assert "inputs" in e and "pdf_path" in e["inputs"] and "txt_path" in e["inputs"]
        et = e["etalon"]
        for key in (
            "bank",
            "account_last4",
            "period",
            "summary",
            "tx_count",
            "reconciled",
        ):
            assert key in et, f"{e['chunk_id']} missing {key}"
        assert "start" in et["period"] and "end" in et["period"]
        s = et["summary"]
        for monetary in (
            "beginning_balance",
            "ending_balance",
            "deposits_total",
            "withdrawals_total",
        ):
            assert isinstance(s[monetary], str), (
                f"{e['chunk_id']}.summary.{monetary} must be a Decimal-encoded string"
            )
        assert isinstance(s["deposits_count"], int)
        assert isinstance(s["withdrawals_count"], int)
        assert et["reconciled"] is True
        # tx_count must equal deposits_count + withdrawals_count (rule 12)
        assert et["tx_count"] == s["deposits_count"] + s["withdrawals_count"], (
            f"{e['chunk_id']}: tx_count != deposits + withdrawals"
        )


def test_period_07_zero_net(entries: list[dict]) -> None:
    """Sep 2024 / account 4623 has deposits == withdrawals == $336,565.07."""
    p7 = next(e for e in entries if e["chunk_id"] == "period_07")
    s = p7["etalon"]["summary"]
    assert s["deposits_total"] == "336565.07"
    assert s["withdrawals_total"] == "336565.07"
    assert s["beginning_balance"] == "-4.00"
    assert s["ending_balance"] == "-4.00"
    assert p7["etalon"]["account_last4"] == "4623"


def test_account_transitions_flagged(entries: list[dict]) -> None:
    """May 2025 (period_02) and Nov 2024 (period_09) carry masked account hints."""
    transitions = {e["chunk_id"]: e["etalon"].get("is_account_transition") for e in entries}
    assert transitions["period_02"] is True
    assert transitions["period_09"] is True
    for cid in (
        "period_01",
        "period_03",
        "period_04",
        "period_05",
        "period_06",
        "period_07",
        "period_08",
        "period_10",
    ):
        assert transitions[cid] is False, f"{cid} should not be a transition"

"""Run all 5 holdout fixtures through the live /extract endpoint and score
each result against tests/fixtures/ground_truth_all.json.

Usage:
    # Stack must be up: docker compose -f infra/docker-compose.yml up -d
    python3 tests/fixtures/run_all.py [http://localhost:8000]

Prints a per-statement scorecard.  Exit 0 = all 5 succeeded (HTTP 200 + a
matching ExtractResult); exit 1 = at least one had a hard mismatch.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from decimal import Decimal
from pathlib import Path

FIXTURES = Path(__file__).parent
GROUND_TRUTH = json.loads((FIXTURES / "ground_truth_all.json").read_text(encoding="utf-8"))
STMT_IDS = [
    "stmt_01_apex_chase",
    "stmt_02_riverstone_bofa",
    "stmt_03_greenfield_wellsfargo",
    "stmt_04_mountainpeak_pnc",
    "stmt_05_aurora_firstpacific",
]


def post_extract(base: str, stmt_id: str) -> dict:
    """POST a stmt's PDF + OCR to /extract and return parsed JSON."""
    pdf = (FIXTURES / f"{stmt_id}.pdf").read_bytes()
    ocr = (FIXTURES / f"{stmt_id}.ocr.txt").read_bytes()

    # Manually build multipart body
    boundary = "----bsa-test-harness"
    parts = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="file"; filename="'
        + f"{stmt_id}.pdf".encode()
        + b'"\r\n',
        b"Content-Type: application/pdf\r\n\r\n",
        pdf,
        f"\r\n--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="ocr_text"; filename="'
        + f"{stmt_id}.ocr.txt".encode()
        + b'"\r\n',
        b"Content-Type: text/plain\r\n\r\n",
        ocr,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    req = urllib.request.Request(
        f"{base}/extract",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def score(stmt_id: str, response: dict) -> dict:
    """Compare response to ground truth; return a dict of pass/fail metrics."""
    gt = GROUND_TRUTH[stmt_id]
    periods = response.get("periods", [])
    if not periods:
        return {"ok": False, "reason": "no periods in response"}

    p = periods[0]
    acc = p["account"]
    summ = p["summary"]
    txs = p["transactions"]

    out = {
        "ok": True,
        "account_last4": (
            acc["account_last4"] == gt["account"]["number_last4"],
            f"{acc['account_last4']} vs {gt['account']['number_last4']}",
        ),
        "period_start": (
            acc["period"]["start"] == gt["period"]["start"],
            f"{acc['period']['start']} vs {gt['period']['start']}",
        ),
        "period_end": (
            acc["period"]["end"] == gt["period"]["end"],
            f"{acc['period']['end']} vs {gt['period']['end']}",
        ),
        "beginning_balance": (
            Decimal(summ["beginning_balance"]) == Decimal(str(gt["summary"]["opening_balance"])),
            f"{summ['beginning_balance']} vs {gt['summary']['opening_balance']}",
        ),
        "ending_balance": (
            Decimal(summ["ending_balance"]) == Decimal(str(gt["summary"]["ending_balance"])),
            f"{summ['ending_balance']} vs {gt['summary']['ending_balance']}",
        ),
        "deposits_total": (
            Decimal(summ["deposits_total"]) == Decimal(str(gt["summary"]["deposits_credits"])),
            f"{summ['deposits_total']} vs {gt['summary']['deposits_credits']}",
        ),
        "withdrawals_total": (
            Decimal(summ["withdrawals_total"]) == Decimal(str(gt["summary"]["withdrawals_debits"])),
            f"{summ['withdrawals_total']} vs {gt['summary']['withdrawals_debits']}",
        ),
        "tx_count": (
            len(txs) == len(gt["transactions"]),
            f"{len(txs)} vs {len(gt['transactions'])}",
        ),
        "reconciled": p["reconciliation"]["reconciled"],
        "delta": p["reconciliation"]["delta"],
        "errors": len(response.get("errors", [])),
    }
    return out


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    rc = 0
    header = (
        f"{'Statement':<35} {'acct':<5} {'beg':<5} {'end':<5} "
        f"{'dep$':<5} {'wd$':<5} {'#tx':<6} {'recon':<5}  delta"
    )
    print(header)
    print("-" * 110)
    for stmt_id in STMT_IDS:
        try:
            resp = post_extract(base, stmt_id)
        except Exception as exc:
            print(f"{stmt_id:<35} ERROR: {exc}")
            rc = 1
            continue
        s = score(stmt_id, resp)
        if not s.get("ok"):
            print(f"{stmt_id:<35} {s['reason']}")
            rc = 1
            continue
        bits = [
            ("acct", s["account_last4"][0]),
            ("beg", s["beginning_balance"][0]),
            ("end", s["ending_balance"][0]),
            ("dep$", s["deposits_total"][0]),
            ("wd$", s["withdrawals_total"][0]),
            ("#tx", s["tx_count"][0]),
        ]
        flags = " ".join(("OK   " if v else "FAIL ") for _, v in bits)
        print(f"{stmt_id:<35} {flags} {s['reconciled']!s:<5}  {s['delta']}")

        # Detail line for any failures
        for name, (ok, detail) in [
            ("account_last4", s["account_last4"]),
            ("period_start", s["period_start"]),
            ("period_end", s["period_end"]),
            ("beginning_balance", s["beginning_balance"]),
            ("ending_balance", s["ending_balance"]),
            ("deposits_total", s["deposits_total"]),
            ("withdrawals_total", s["withdrawals_total"]),
            ("tx_count", s["tx_count"]),
        ]:
            if not ok:
                print(f"  ~ {name}: {detail}")
                rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())

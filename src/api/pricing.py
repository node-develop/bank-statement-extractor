"""LLM pricing table + hard cost cap.

Single source for all cost-control constants.  Imported by:

- ``src/nodes/route_after_verifier`` (in ``src/nodes/critic_loop.py``) to
  decide when to short-circuit to ``await_review``.
- Every LLM-using node (``classify_layout``, ``extract_account``,
  ``extract_summary``, ``extract_transactions``, ``critic_loop``) for
  inline ``call_cost`` increments returned in their state delta.

Pricing is the May-2026 published rate per million tokens for each
Anthropic model in use.  Values are quoted as ``Decimal`` to avoid float
drift when summed across the fan-out.
"""

from __future__ import annotations

import os
from decimal import Decimal

PRICING_USD_PER_M_TOKENS: dict[str, dict[str, Decimal]] = {
    "claude-haiku-4-5": {"input": Decimal("0.25"), "output": Decimal("1.25")},
    "claude-sonnet-4-6": {"input": Decimal("3.00"), "output": Decimal("15.00")},
}

# Abort the request when cumulative LLM spend reaches this dollar value.
# Overridable via env so tests + pathological statements can tighten/relax it.
HARD_COST_CAP_USD: Decimal = Decimal(os.environ.get("BSA_COST_CAP_USD", "5.00"))


def call_cost(model: str, usage: dict[str, int] | None) -> Decimal:
    """Return the dollar cost of one LLM call given its usage_metadata dict.

    ``usage`` is the dict returned by langchain on ``response.usage_metadata``.
    Unknown keys are treated as zero so callers don't need to defend.

    Unknown models are silently priced as zero (and logged at WARNING by the
    caller if it cares) — this keeps the cumulative-cost accumulator running
    under unexpected model identifiers rather than throwing.
    """
    table = PRICING_USD_PER_M_TOKENS.get(model)
    if table is None or not usage:
        return Decimal("0")
    in_tok = Decimal(usage.get("input_tokens", 0) or 0)
    out_tok = Decimal(usage.get("output_tokens", 0) or 0)
    cost = (in_tok * table["input"]) + (out_tok * table["output"])
    return cost / Decimal("1000000")

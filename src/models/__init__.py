"""Pydantic v2 value-object models for the bank-statement-analizer.

All money fields use ``decimal.Decimal`` — never float.
Dates are ``datetime.date`` internally; the wire schema serializes them as
ISO 8601 strings (``YYYY-MM-DD``) via ``field_serializer``.
Decimal fields are serialized to JSON as **quoted strings** quantized to two
decimal places (e.g. ``"597068.70"``).  This follows the ISO 20022 / OFX /
XBRL convention and prevents float-representation drift when clients
round-trip the value back through ``Decimal``.  Clients must parse monetary
strings with a decimal library (e.g. Python ``Decimal``, JS ``decimal.js``).

Re-exports:
    EPSILON -- reconciliation tolerance: Decimal("0.01")
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_serializer,
    field_validator,
)

if TYPE_CHECKING:
    import datetime
from datetime import date  # runtime-required by Pydantic v2 field annotations

__all__ = [
    "EPSILON",
    "Account",
    "ExtractResult",
    "LayoutLabel",
    "Period",
    "PeriodChunk",
    "PeriodResult",
    "RawStatement",
    "Reconciliation",
    "Summary",
    "Transaction",
]

# ---------------------------------------------------------------------------
# Module-level constant — reconciliation tolerance
# ---------------------------------------------------------------------------
EPSILON: Decimal = Decimal("0.01")

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
_TWO_PLACES = Decimal("0.01")


def _quantize(value: Decimal) -> Decimal:
    """Return *value* rounded to two decimal places (ROUND_HALF_UP)."""
    return value.quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _coerce_to_decimal(v: object, field_name: str = "value") -> Decimal:
    """Coerce int/str/Decimal to Decimal; reject float."""
    if isinstance(v, float):
        raise ValueError(f"{field_name}: float is prohibited; pass Decimal or str instead")
    return _quantize(Decimal(str(v)))


# ---------------------------------------------------------------------------
# Shared model config for immutable value objects
# ---------------------------------------------------------------------------
_VALUE_CFG: ConfigDict = ConfigDict(strict=True, frozen=True)


# ---------------------------------------------------------------------------
# Period
# ---------------------------------------------------------------------------
class Period(BaseModel):
    """Inclusive calendar period for a single bank-statement month."""

    model_config = _VALUE_CFG

    start: date
    end: date

    @field_validator("start", "end", mode="before")
    @classmethod
    def _coerce_iso_date(cls, v: object) -> object:
        """Accept ISO-8601 strings from LLM structured output.

        ``model_config=strict=True`` would otherwise reject any string
        when the field is typed ``date``.  LLMs return dates as strings
        in their JSON output; LangChain ``with_structured_output``
        delivers them as-is via ``model_validate`` in Python (strict) mode.
        """
        if isinstance(v, str):
            return date.fromisoformat(v)
        return v

    @field_validator("end")
    @classmethod
    def end_not_before_start(cls, v: date, info: ValidationInfo) -> date:
        start: date | None = (info.data or {}).get("start")
        if start is not None and v < start:
            raise ValueError(f"end ({v}) must be >= start ({start})")
        return v

    @field_serializer("start", "end")
    def _serialize_date(self, v: date) -> str:
        return v.isoformat()


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------
class Account(BaseModel):
    """Identifying information for one bank account / statement period."""

    model_config = _VALUE_CFG

    chunk_id: str
    bank: str
    account_last4: str = Field(pattern=r"^\d{4}$")
    period: Period


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
class Summary(BaseModel):
    """Period-level monetary summary extracted from the statement header."""

    model_config = _VALUE_CFG

    chunk_id: str
    beginning_balance: Decimal
    ending_balance: Decimal
    deposits_total: Decimal
    deposits_count: int = Field(ge=0)
    withdrawals_total: Decimal
    withdrawals_count: int = Field(ge=0)

    @field_validator(
        "beginning_balance",
        "ending_balance",
        "deposits_total",
        "withdrawals_total",
        mode="before",
    )
    @classmethod
    def _coerce_decimal(cls, v: object) -> Decimal:
        """Accept int / str / Decimal; always return Decimal quantized to 2dp."""
        return _coerce_to_decimal(v)

    @field_serializer(
        "beginning_balance",
        "ending_balance",
        "deposits_total",
        "withdrawals_total",
    )
    def _serialize_decimal(self, v: Decimal) -> str:
        # Quoted string prevents float-representation drift on round-trips.
        # Value is already quantized to 2dp by _coerce_decimal — str() is exact.
        return str(v)


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------
class Transaction(BaseModel):
    """A single line-item debit or credit on the statement."""

    model_config = _VALUE_CFG

    chunk_id: str
    date: date
    description: str
    amount: Decimal  # non-negative; sign conveyed by ``direction``
    direction: Literal["credit", "debit"]
    running_balance: Decimal | None = None

    @field_validator("date", mode="before")
    @classmethod
    def _coerce_iso_date(cls, v: object) -> object:
        """Accept ISO-8601 strings from LLM structured output (strict=True)."""
        if isinstance(v, str):
            return date.fromisoformat(v)
        return v

    @field_validator("amount", mode="before")
    @classmethod
    def _coerce_amount(cls, v: object) -> Decimal:
        d = _coerce_to_decimal(v, "amount")
        if d < Decimal("0"):
            raise ValueError(f"amount must be >= 0, got {d!r}")
        return d

    @field_validator("running_balance", mode="before")
    @classmethod
    def _coerce_running_balance(cls, v: object) -> Decimal | None:
        if v is None:
            return None
        return _coerce_to_decimal(v, "running_balance")

    @field_serializer("date")
    def _serialize_date(self, v: datetime.date) -> str:
        return v.isoformat()

    @field_serializer("amount")
    def _serialize_amount(self, v: Decimal) -> str:
        return str(v)

    @field_serializer("running_balance")
    def _serialize_running_balance(self, v: Decimal | None) -> str | None:
        return str(v) if v is not None else None


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------
class Reconciliation(BaseModel):
    """Outcome of the pure-Python reconciliation step for one period chunk."""

    model_config = _VALUE_CFG

    chunk_id: str
    reconciled: bool
    delta: Decimal  # |actual_ending - computed_ending|; Decimal("0.00") when reconciled
    notes: list[str]

    @field_validator("delta", mode="before")
    @classmethod
    def _coerce_delta(cls, v: object) -> Decimal:
        return _coerce_to_decimal(v, "delta")

    @field_serializer("delta")
    def _serialize_delta(self, v: Decimal) -> str:
        return str(v)


# ---------------------------------------------------------------------------
# RawStatement
# ---------------------------------------------------------------------------
class RawStatement(BaseModel):
    """Raw extraction from a PDF (plus optional OCR text) before any parsing."""

    model_config = ConfigDict(strict=True, frozen=True)

    pages: list[str]  # per-page text after pdfplumber + OCR source-selection
    ocr_text: str | None  # full OCR dump; None if not provided
    sha256: str  # hex digest of the original PDF bytes
    page_count: int = Field(gt=0)

    @field_validator("page_count")
    @classmethod
    def _page_count_matches(cls, v: int, info: ValidationInfo) -> int:
        pages: list[str] | None = (info.data or {}).get("pages")
        if pages is not None and v != len(pages):
            raise ValueError(f"page_count ({v}) must equal len(pages) ({len(pages)})")
        return v


# ---------------------------------------------------------------------------
# PeriodChunk
# ---------------------------------------------------------------------------
class PeriodChunk(BaseModel):
    """One period's worth of raw text, ready for the extractor fan-out.

    ``chunk_id`` is a stable string key (e.g. ``"period_01"``) used by
    all downstream reducers to stitch fan-out results back to the originating
    period.
    """

    model_config = ConfigDict(strict=True, frozen=True)

    chunk_id: str
    page_range: tuple[int, int]  # inclusive (first_page, last_page), 1-indexed
    pdf_text: str
    ocr_slice: str | None
    account_hint_last4: str | None = None

    @field_validator("account_hint_last4")
    @classmethod
    def _validate_hint(cls, v: str | None) -> str | None:
        """Validate that if provided, account_hint_last4 is exactly 4 digits."""
        if v is not None and (len(v) != 4 or not v.isdigit()):
            raise ValueError(f"account_hint_last4 must be exactly 4 digits, got {v!r}")
        return v


# ---------------------------------------------------------------------------
# LayoutLabel
# ---------------------------------------------------------------------------
class LayoutLabel(BaseModel):
    """Layout classification result produced by ``classify_layout`` per chunk."""

    model_config = _VALUE_CFG

    chunk_id: str
    label: Literal["ixonia_business_basic", "generic_us_bank", "unknown"]


# ---------------------------------------------------------------------------
# PeriodResult
# ---------------------------------------------------------------------------
class PeriodResult(BaseModel):
    """Terminal per-period record assembled by ``finalize``."""

    model_config = ConfigDict(strict=True, frozen=True)

    chunk_id: str
    account: Account
    summary: Summary
    transactions: list[Transaction]
    layout: str
    reconciliation: Reconciliation


# ---------------------------------------------------------------------------
# ExtractResult  (top-level API response)
# ---------------------------------------------------------------------------
class ExtractResult(BaseModel):
    """Top-level response returned from POST /extract."""

    model_config = ConfigDict(strict=False, frozen=False)  # mutable for assembly

    periods: list[PeriodResult]
    statement_sha256: str
    langsmith_run_url: str | None = None
    errors: list[str] = Field(default_factory=list)

"""Enum types used by the accounting engine."""

from __future__ import annotations

from enum import StrEnum


class FundCode(StrEnum):
    """Supported fund codes."""
    OPERATING = "OPERATING"
    RESERVE = "RESERVE"
    SPECIAL = "SPECIAL"


class PaymentMethod(StrEnum):
    """Supported owner payment methods."""
    CHECK = "CHECK"
    ACH = "ACH"
    CASH = "CASH"
    CARD = "CARD"
    OTHER = "OTHER"


class SourceType(StrEnum):
    """Supported journal source types."""
    ASSESSMENT = "ASSESSMENT"
    PAYMENT = "PAYMENT"
    VENDOR_BILL = "VENDOR_BILL"
    BILL_PAYMENT = "BILL_PAYMENT"
    TRANSFER = "TRANSFER"
    ADJUSTMENT = "ADJUSTMENT"
    REVERSAL = "REVERSAL"
    MANUAL = "MANUAL"
    OPENING_BALANCE = "OPENING_BALANCE"

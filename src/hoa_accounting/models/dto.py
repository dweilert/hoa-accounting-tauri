"""Data transfer objects used by services."""

from __future__ import annotations

from dataclasses import dataclass

# ── Single-entry transaction results ──────────────────────────────────────────


@dataclass(frozen=True)
class AssessmentResult:
    assessment_id: int


@dataclass(frozen=True)
class PaymentResult:
    payment_id: int


@dataclass(frozen=True)
class VendorBillResult:
    vendor_bill_id: int


@dataclass(frozen=True)
class VendorPaymentResult:
    bill_payment_id: int


@dataclass(frozen=True)
class ReserveTransferResult:
    reserve_transfer_id: int

"""Smoke tests for the reportlab-based owner-ledger PDF builder.

Verifies that ``render_owner_ledger_pdf`` produces valid PDF bytes
across the realistic shape variations: empty rows, multiple owners,
opening-balance breakdown present/absent, status/type pill branches,
and the no-activity placeholder.
"""

from __future__ import annotations

from hoa_accounting.reporting.owner_ledger_pdf import render_owner_ledger_pdf


def _base_summary() -> dict[str, object]:
    return {
        "lot_number": "L-1",
        "lot_address": "123 Test Way",
        "owners": [
            {
                "first_name": "Alice",
                "last_name": "Park",
                "display_name": "Alice Park",
                "email": "alice@example.com",
                "phone": "555-0101",
            }
        ],
        "year": "2026",
        "opening_balance": "0.00",
        "closing_balance": "0.00",
        "opening_balance_lines": [],
        "rows": [],
        "generated_at": "4/28/2026 1:00 PM",
    }


def test_render_minimal_pdf():
    """Empty-rows path produces a valid PDF with the no-activity placeholder."""
    pdf = render_owner_ledger_pdf(_base_summary())
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000  # has actual content, not just header


def test_render_with_transactions():
    s = _base_summary()
    s["opening_balance"] = "250.00"
    s["closing_balance"] = "0.00"
    s["opening_balance_lines"] = [
        {"charge_type": "DUES", "label": "Dues", "amount": "200.00"},
        {"charge_type": "LATE_FEE", "label": "Late Fees", "amount": "50.00"},
    ]
    s["rows"] = [
        {
            "entry_date": "2026-01-15",
            "entry_type": "CHARGE",
            "charge_type": "DUES",
            "description": "January dues",
            "due_date": "2026-01-15",
            "status": "OPEN",
            "receipt_number": "",
            "debit_amount": "100.00",
            "credit_amount": "0.00",
            "running_balance": "100.00",
        },
        {
            "entry_date": "2026-01-20",
            "entry_type": "PAYMENT",
            "charge_type": "DUES",
            "description": "Payment received",
            "due_date": "",
            "status": "PAID",
            "receipt_number": "RCT-2026-0001",
            "debit_amount": "0.00",
            "credit_amount": "100.00",
            "running_balance": "0.00",
        },
    ]
    pdf = render_owner_ledger_pdf(s)
    assert pdf.startswith(b"%PDF-")
    # Should be larger than the empty-row case.
    empty = render_owner_ledger_pdf(_base_summary())
    assert len(pdf) > len(empty)


def test_render_late_and_legal_fee_pills():
    """The type-pill branch covers LATE_FEE and LEGAL_FEE — exercise both."""
    s = _base_summary()
    s["rows"] = [
        {
            "entry_date": "2026-02-01",
            "entry_type": "CHARGE",
            "charge_type": "LATE_FEE",
            "description": "Late fee for January",
            "due_date": "2026-02-15",
            "status": "OPEN",
            "receipt_number": "",
            "debit_amount": "25.00",
            "credit_amount": "0.00",
            "running_balance": "25.00",
        },
        {
            "entry_date": "2026-03-01",
            "entry_type": "CHARGE",
            "charge_type": "LEGAL_FEE",
            "description": "Legal fee",
            "due_date": "2026-03-15",
            "status": "OPEN",
            "receipt_number": "",
            "debit_amount": "100.00",
            "credit_amount": "0.00",
            "running_balance": "125.00",
        },
        {
            "entry_date": "2026-03-10",
            "entry_type": "ADJUSTMENT",
            "charge_type": "MISC",
            "description": "Adjustment",
            "due_date": "",
            "status": "",
            "receipt_number": "",
            "debit_amount": "0.00",
            "credit_amount": "10.00",
            "running_balance": "115.00",
        },
    ]
    s["closing_balance"] = "115.00"
    pdf = render_owner_ledger_pdf(s)
    assert pdf.startswith(b"%PDF-")


def test_render_multiple_owners():
    s = _base_summary()
    s["owners"] = [
        {
            "first_name": "Alice",
            "last_name": "Park",
            "display_name": "Alice Park",
            "email": "alice@example.com",
            "phone": "",
        },
        {
            "first_name": "Bob",
            "last_name": "Lee",
            "display_name": "Bob Lee",
            "email": "",
            "phone": "555-0202",
        },
    ]
    pdf = render_owner_ledger_pdf(s)
    assert pdf.startswith(b"%PDF-")


def test_render_no_owners():
    """Owner block is optional — absent owners shouldn't crash."""
    s = _base_summary()
    s["owners"] = []
    pdf = render_owner_ledger_pdf(s)
    assert pdf.startswith(b"%PDF-")


def test_render_no_address():
    s = _base_summary()
    s["lot_address"] = ""
    pdf = render_owner_ledger_pdf(s)
    assert pdf.startswith(b"%PDF-")


def test_render_no_generated_at():
    s = _base_summary()
    del s["generated_at"]
    pdf = render_owner_ledger_pdf(s)
    assert pdf.startswith(b"%PDF-")

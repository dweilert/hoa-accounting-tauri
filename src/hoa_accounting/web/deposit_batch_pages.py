"""Deposit-batch list page + batch entry form.

Lets a treasurer enter a whole stack of owner checks on one page.
Running total reflects the deposit slip the checks are going to the
bank with. Form POST collapses all rows into a single call to
``DepositBatchService.post_batch``.

Rows with no amount are silently dropped (common when the operator
pre-filled a few blank rows for convenience). Validation errors get
surfaced as a single alert at the top; the form re-renders with every
submitted value intact so the treasurer doesn't lose work.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from typing import Sequence

from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.deposit_batches_repo import DepositBatchesRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.services.deposit_batch_service import DepositRow
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template
from hoa_accounting.validators.forms import parse_int as _parse_int, parse_positive_decimal as _parse_positive_decimal, require as _require


@dataclass(frozen=True)
class BatchPageResponse:
    status_code: int
    body_html: str


def _today() -> str:
    return _date.today().isoformat()


_ROW_KEY_RE = re.compile(r"^row_(\d+)_(lot_id|amount|reference_number|memo)$")


class DepositBatchPages:
    """Render and submit the deposit-batch UI."""

    LIST_TEMPLATE = "deposit_batches_list.html"
    FORM_TEMPLATE = "deposit_batch_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.factory = ServiceFactory(conn)

    # ── List page ───────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        created_entry_number: str | None = None,
    ) -> BatchPageResponse:
        rows = DepositBatchesRepository(self.conn).list_batches()
        batches = [
            {
                "id": r["id"],
                "deposit_date": r["deposit_date"],
                "total_amount": f"{Decimal(str(r['total_amount'])):.2f}",
                "bank_account": r["bank_account_name"],
                "institution": r["institution_name"],
                "entry_number": r["entry_number"] or "",
                "payment_count": int(r["payment_count"]),
                "notes": r["notes"] or "",
            }
            for r in rows
        ]
        ctx = {
            "heading": "Deposits",
            "description": (
                "Batched owner payments. Each row represents one trip "
                "to the bank — payments are summed into a single cash "
                "entry on your books so it matches what shows up on "
                "the bank statement."
            ),
            "batches": batches,
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "deposits",
            "breadcrumb": "Transactions",
            "created_entry_number": created_entry_number,
        }
        return BatchPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Form page ───────────────────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        form_values: dict[str, str] | None = None,
        submitted_rows: list[dict[str, str]] | None = None,
        error_message: str = "",
    ) -> BatchPageResponse:
        values = form_values or {}

        # Resolve the posting AR account from config and show it read-only
        # AR account resolution removed — payments now apply directly to
        # assessments by category (no GL receivable account).
        resolved_error = error_message
        ar_account_label = ""

        banks = [
            {
                "id": r["id"],
                "label": f"{r['account_name']} · {r['institution_name']}"
                         + (f" (…{r['account_last4']})" if r["account_last4"] else ""),
            }
            for r in BankAccountsRepository(self.conn).list_bank_accounts()
        ]
        lots = [
            {"id": r["id"], "label": _lot_label(r)}
            for r in LotsRepository(self.conn).list_lots()
        ]

        # Preserve submitted rows (after a validation error) or start with
        # a handful of blank rows as scratchpad.
        rows_for_render = submitted_rows or [
            {"lot_id": "", "amount": "", "reference_number": "", "memo": ""}
            for _ in range(5)
        ]

        ctx = {
            "heading": "New Deposit Batch",
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "deposits",
            "breadcrumb": "Transactions · Deposits",
            "banks": banks,
            "lots": lots,
            "ar_account_label": ar_account_label,
            "rows": rows_for_render,
            "values": {
                "deposit_date": values.get("deposit_date", _today()),
                "bank_account_id": values.get("bank_account_id", ""),
                "notes": values.get("notes", ""),
            },
            "error_message": resolved_error,
        }
        status = HTTPStatus.BAD_REQUEST if resolved_error else HTTPStatus.OK
        return BatchPageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Form POST ───────────────────────────────────────────────────

    def handle_post(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, BatchPageResponse | None]:
        # Extract per-row fields into an indexed dict.
        by_index: dict[int, dict[str, str]] = {}
        for key, value in form_data.items():
            m = _ROW_KEY_RE.match(key)
            if not m:
                continue
            idx = int(m.group(1))
            by_index.setdefault(idx, {})[m.group(2)] = value
        # Order by index so re-render preserves row order.
        submitted_rows = [by_index[i] for i in sorted(by_index)]

        # Now filter out entirely-blank rows (no amount AND no lot). This
        # lets the treasurer leave pre-filled empty scratchpad rows.
        active_rows = [
            r for r in submitted_rows
            if (r.get("amount") or "").strip() or (r.get("lot_id") or "").strip()
        ]

        try:
            deposit_date = _require(form_data.get("deposit_date", ""), "Deposit date")
            bank_account_id = _parse_int(
                form_data.get("bank_account_id", ""), "Bank account"
            )
            notes = (form_data.get("notes", "") or "").strip() or None

            if not active_rows:
                raise ValidationError(
                    "Enter at least one payment row with a lot and amount."
                )

            deposit_rows: list[DepositRow] = []
            for i, r in enumerate(active_rows, start=1):
                lot_id = _parse_int(r.get("lot_id", ""), f"Row {i}: lot")
                amount = _parse_positive_decimal(
                    r.get("amount", ""), f"Row {i}: amount"
                )
                deposit_rows.append(
                    DepositRow(
                        lot_id=lot_id,
                        amount=amount,
                        reference_number=(r.get("reference_number") or "").strip() or None,
                        memo=(r.get("memo") or "").strip() or None,
                    )
                )

            result = self.factory.deposit_batch_service().post_batch(
                deposit_date=deposit_date,
                bank_account_id=bank_account_id,
                rows=deposit_rows,
                notes=notes,
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_form(
                org=org,
                theme=theme,
                form_values=form_data,
                submitted_rows=submitted_rows or None,
                error_message=str(exc),
            )
            return (None, resp)

        return (f"/deposits?created={result.deposit_batch_id}", None)


# ── Helpers ────────────────────────────────────────────────────────


def _lot_label(row: sqlite3.Row) -> str:
    """Format a lot dropdown label as 'L-1 · 100 Pine · Alice Park'."""
    street = row["street_address_1"] or ""
    owner = row["owner_names"] or "(no current owner)"
    bits = [str(row["lot_number"])]
    if street:
        bits.append(street)
    bits.append(owner)
    return " · ".join(bits)



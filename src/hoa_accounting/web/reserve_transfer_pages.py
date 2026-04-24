"""Page-service for reserve transfers."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from hoa_accounting.exceptions import ClosedPeriodError, ValidationError
from hoa_accounting.repositories.reserve_transfers_repo import ReserveTransfersRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


_TYPE_LABELS = {
    "FUND":     "Fund Reserve  (Operating → Reserve)",
    "WITHDRAW": "Reserve Withdrawal  (Reserve → Operating)",
}


class ReserveTransferPages:
    """Handles reserve transfer page rendering and mutations."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._repo = ReserveTransfersRepository(conn)
        self._factory = ServiceFactory(conn)

    # ── Helpers ────────────────────────────────────────────────────────

    def _render(self, template: str, **ctx) -> PageResponse:
        return PageResponse(200, render_template(template, ctx))

    def _render_error(self, status: int, msg: str, org: dict, theme: str) -> PageResponse:
        return PageResponse(status, render_template("error.html", {
            "org": org, "theme": theme,
            "heading": "Error", "message": msg,
            "page_key": "reserve-transfers",
        }))

    # ── List ───────────────────────────────────────────────────────────

    def render_list(
        self,
        org: dict,
        theme: str,
        type_filter: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        flash_message: str | None = None,
        error_message: str | None = None,
    ) -> PageResponse:
        rows = self._repo.list_transfers(
            type_filter=type_filter,
            start_date=start_date,
            end_date=end_date,
        )
        reserve_balance = self._repo.get_reserve_balance()
        return self._render(
            "reserve_transfers_list.html",
            org=org, theme=theme,
            page_key="reserve-transfers",
            heading="Reserve Transfers",
            rows=rows,
            row_count=len(rows),
            reserve_balance=reserve_balance,
            type_filter=type_filter or "",
            start_date=start_date or "",
            end_date=end_date or "",
            type_labels=_TYPE_LABELS,
            flash_message=flash_message,
            error_message=error_message,
        )

    # ── New form ───────────────────────────────────────────────────────

    def render_new_form(
        self,
        org: dict,
        theme: str,
        error: str | None = None,
        values: dict | None = None,
    ) -> PageResponse:
        return self._render(
            "reserve_transfer_new.html",
            org=org, theme=theme,
            page_key="reserve-transfers",
            heading="New Reserve Transfer",
            error=error,
            values=values or {},
            type_labels=_TYPE_LABELS,
        )

    def handle_new(
        self,
        form_data: dict,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        transfer_type = form_data.get("transfer_type", "").strip()
        transfer_date = form_data.get("transfer_date", "").strip()
        amount_raw = form_data.get("amount", "").strip()
        purpose = form_data.get("purpose", "").strip()
        notes = form_data.get("notes", "").strip()

        def _err(msg: str) -> tuple[str | None, PageResponse | None]:
            return None, self.render_new_form(org, theme, error=msg, values=form_data)

        if transfer_type not in ("FUND", "WITHDRAW"):
            return _err("Please select a transfer type.")
        if not transfer_date:
            return _err("Transfer date is required.")
        try:
            amount = Decimal(amount_raw.replace(",", ""))
            if amount <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            return _err("Amount must be a positive number.")
        if not notes:
            return _err("Notes are required.")
        if transfer_type == "WITHDRAW" and not purpose:
            return _err("Purpose is required for reserve withdrawals.")

        memo = purpose or notes or (
            "Fund Reserve transfer" if transfer_type == "FUND" else "Reserve withdrawal"
        )

        try:
            svc = self._factory.reserve_transfer_service()
            svc.post_reserve_transfer(
                entry_date=transfer_date,
                amount=amount,
                description=memo,
                transfer_type=transfer_type,
                purpose=purpose or None,
                created_by_user_id=None,
            )
            self._conn.commit()
        except (ValidationError, ClosedPeriodError) as exc:
            self._conn.rollback()
            return _err(str(exc))
        except Exception:
            self._conn.rollback()
            raise

        label = "funded" if transfer_type == "FUND" else "withdrawal recorded"
        return f"/reserve-transfers?msg=Reserve+transfer+{label}.", None

    # ── Delete ─────────────────────────────────────────────────────────

    def handle_delete(
        self,
        transfer_id: int,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        row = self._repo.get_transfer(transfer_id)
        if not row:
            return None, self._render_error(404, "Transfer not found.", org, theme)

        cleared = self._conn.execute(
            """
            SELECT COUNT(*) FROM reconciliation_clears rc
            JOIN bank_transactions bt ON bt.id = rc.bank_transaction_id
            WHERE bt.matched_source_type = 'RESERVE_TRANSFER'
              AND bt.matched_source_id   = ?
            """,
            (transfer_id,),
        ).fetchone()
        if cleared and int(cleared[0]) > 0:
            return (
                "/reserve-transfers?error=Cannot+delete+a+transfer+that+has+been+reconciled.",
                None,
            )

        self._repo.delete_transfer(transfer_id)
        return "/reserve-transfers?msg=Transfer+deleted.", None

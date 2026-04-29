"""Page-service for bank reconciliation."""

from __future__ import annotations
from typing import Any

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from hoa_accounting.repositories.reconciliation_repo import ReconciliationRepository
from hoa_accounting.validators.format import format_currency
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


class ReconciliationPages:
    """Handles all bank-reconciliation page rendering and mutations."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._repo = ReconciliationRepository(conn)

    # ── Helpers ────────────────────────────────────────────────────────

    def _render(self, template: str, **ctx: Any) -> PageResponse:
        return PageResponse(200, render_template(template, ctx))

    def _render_404(self, msg: str, org: dict[str, Any], theme: str) -> PageResponse:
        return PageResponse(
            404,
            render_template(
                "error.html",
                {
                    "org": org,
                    "theme": theme,
                    "heading": "Not Found",
                    "message": msg,
                    "page_key": "reconciliations",
                },
            ),
        )

    @staticmethod
    def _parse_amount(raw: str) -> Decimal | None:
        try:
            return Decimal(raw.replace(",", "").strip())
        except (InvalidOperation, AttributeError):
            return None

    # ── List ───────────────────────────────────────────────────────────

    def render_list(
        self,
        org: dict[str, Any],
        theme: str,
        flash_message: str | None = None,
        error_message: str | None = None,
    ) -> PageResponse:
        rows = self._repo.list_reconciliations()
        return self._render(
            "reconciliations_list.html",
            org=org,
            theme=theme,
            page_key="reconciliations",
            heading="Bank Reconciliations",
            rows=rows,
            row_count=len(rows),
            flash_message=flash_message,
            error_message=error_message,
        )

    # ── New form ───────────────────────────────────────────────────────

    def render_new_form(
        self,
        org: dict[str, Any],
        theme: str,
        error: str | None = None,
        values: dict[str, Any] | None = None,
    ) -> PageResponse:
        bank_accounts = self._repo.list_active_bank_accounts()

        # Pre-compute expected beginning balance for each bank account
        # so the form can auto-populate via JS when the user picks one.
        beginning_balances: dict[int, dict[str, Any]] = {}
        for ba in bank_accounts:
            bal, label = self._repo.get_expected_beginning_balance(int(ba["id"]))
            beginning_balances[int(ba["id"])] = {
                "amount": str(bal),
                "label": label,
            }

        return self._render(
            "reconciliation_new.html",
            org=org,
            theme=theme,
            page_key="reconciliations",
            heading="New Bank Reconciliation",
            bank_accounts=bank_accounts,
            beginning_balances=beginning_balances,
            error=error,
            values=values or {},
        )

    def handle_new(
        self,
        form_data: dict[str, Any],
        org: dict[str, Any],
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        bank_account_id_raw = form_data.get("bank_account_id", "").strip()
        statement_date = form_data.get("statement_date", "").strip()
        statement_balance_raw = form_data.get("statement_balance", "").strip()

        # Validate
        if not bank_account_id_raw or not bank_account_id_raw.isdigit():
            return None, self.render_new_form(
                org, theme,
                error="Please select a bank account.",
                values=form_data,
            )
        if not statement_date:
            return None, self.render_new_form(
                org, theme,
                error="Statement date is required.",
                values=form_data,
            )
        balance = self._parse_amount(statement_balance_raw)
        if balance is None:
            return None, self.render_new_form(
                org, theme,
                error="Statement ending balance must be a number.",
                values=form_data,
            )

        beginning_balance_raw = form_data.get("beginning_balance", "").strip()
        beginning_balance = self._parse_amount(beginning_balance_raw) if beginning_balance_raw else None

        bank_account_id = int(bank_account_id_raw)

        # Check for duplicate (same account + statement date)
        existing = self._conn.execute(
            """SELECT id FROM bank_reconciliations
               WHERE bank_account_id = ? AND statement_ending_date = ?""",
            (bank_account_id, statement_date),
        ).fetchone()
        if existing:
            return None, self.render_new_form(
                org, theme,
                error="A reconciliation for this account and statement date already exists.",
                values=form_data,
            )

        recon_id = self._repo.insert_reconciliation(
            bank_account_id=bank_account_id,
            statement_ending_date=statement_date,
            statement_ending_balance=str(balance),
            statement_beginning_balance=str(beginning_balance) if beginning_balance is not None else None,
        )
        return f"/reconciliations/{recon_id}", None

    # ── Working screen ─────────────────────────────────────────────────

    def render_working(
        self,
        reconciliation_id: int,
        org: dict[str, Any],
        theme: str,
        show_prior: bool = False,
        flash_message: str | None = None,
    ) -> PageResponse:
        recon = self._repo.get_reconciliation(reconciliation_id)
        if not recon:
            return self._render_404("Reconciliation not found.", org, theme)

        rows = self._repo.get_working_rows(reconciliation_id)
        summary = self._repo.get_balance_summary(reconciliation_id)

        is_open = recon["status"] == "OPEN"
        pending_import = None  # imports are no longer scoped to reconciliations

        # Beginning balance mismatch warning
        beginning_balance_warning: str | None = None
        stmt_beg = recon["statement_beginning_balance"]
        if stmt_beg is not None:
            expected, expected_label = self._repo.get_expected_beginning_balance(
                int(recon["bank_account_id"])
            )
            actual = Decimal(str(stmt_beg))
            if actual != expected:
                beginning_balance_warning = (
                    f"Statement beginning balance ({format_currency(actual)}) does not match "
                    f"the expected {expected_label} ({format_currency(expected)}). "
                    f"Please verify before completing."
                )

        return self._render(
            "reconciliation_work.html",
            org=org,
            theme=theme,
            page_key="reconciliations",
            heading=f"Reconcile · {recon['account_name']}",
            recon=recon,
            rows=rows,
            summary=summary,
            is_open=is_open,
            show_prior=show_prior,
            flash_message=flash_message,
            beginning_balance_warning=beginning_balance_warning,
            pending_import=dict(pending_import) if pending_import else None,
        )

    # ── Toggle (AJAX) ──────────────────────────────────────────────────

    def handle_toggle(
        self,
        reconciliation_id: int,
        form_data: dict[str, Any],
    ) -> tuple[int, str]:
        """Toggle a JE line's cleared state.  Returns (http_status, json_body)."""
        recon = self._repo.get_reconciliation(reconciliation_id)
        if not recon:
            return 404, json.dumps({"error": "Not found"})
        if recon["status"] != "OPEN":
            return 400, json.dumps({"error": "Reconciliation is not open"})

        source_type = str(form_data.get("source_type") or "").strip().upper()
        source_id_raw = form_data.get("source_id", "")
        if source_type not in {
            "PAYMENT", "INCOME_BATCH", "BILL_PAYMENT", "RESERVE_TRANSFER"
        }:
            return 400, json.dumps({"error": "Invalid source_type"})
        if not str(source_id_raw).isdigit():
            return 400, json.dumps({"error": "Invalid source_id"})
        source_id = int(source_id_raw)

        cleared = form_data.get("cleared") in ("1", "true", True)
        if cleared:
            self._repo.clear_item(reconciliation_id, source_type, source_id)
        else:
            self._repo.unclear_item(reconciliation_id, source_type, source_id)

        summary = self._repo.get_balance_summary(reconciliation_id)
        return 200, json.dumps(summary)

    # ── Finalize ───────────────────────────────────────────────────────

    def handle_finalize(
        self,
        reconciliation_id: int,
        org: dict[str, Any],
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        recon = self._repo.get_reconciliation(reconciliation_id)
        if not recon:
            return None, self._render_404("Reconciliation not found.", org, theme)

        summary = self._repo.get_balance_summary(reconciliation_id)
        if not summary.get("balanced"):
            return (
                f"/reconciliations/{reconciliation_id}"
                "?error=Cannot+complete+reconciliation+while+difference+is+not+zero.",
                None,
            )

        self._repo.finalize_reconciliation(
            reconciliation_id, str(summary["book_balance"])
        )
        return (
            f"/reconciliations?msg=Reconciliation+completed+successfully.",
            None,
        )

    # ── Reopen ─────────────────────────────────────────────────────────

    def handle_reopen(
        self,
        reconciliation_id: int,
        org: dict[str, Any],
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        recon = self._repo.get_reconciliation(reconciliation_id)
        if not recon:
            return None, self._render_404("Reconciliation not found.", org, theme)
        self._repo.reopen_reconciliation(reconciliation_id)
        return f"/reconciliations/{reconciliation_id}", None

    # ── Delete ─────────────────────────────────────────────────────────

    def handle_delete(
        self,
        reconciliation_id: int,
        org: dict[str, Any],
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        recon = self._repo.get_reconciliation(reconciliation_id)
        if not recon:
            return None, self._render_404("Reconciliation not found.", org, theme)
        if recon["status"] == "FINALIZED":
            return (
                "/reconciliations?error=Cannot+delete+a+finalized+reconciliation.",
                None,
            )
        self._repo.delete_reconciliation(reconciliation_id)
        return "/reconciliations?msg=Reconciliation+deleted.", None

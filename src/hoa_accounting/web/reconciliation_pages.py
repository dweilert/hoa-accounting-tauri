"""Page-service for bank reconciliation."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from hoa_accounting.repositories.reconciliation_repo import ReconciliationRepository
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

    def _render(self, template: str, **ctx) -> PageResponse:
        return PageResponse(200, render_template(template, ctx))

    def _render_404(self, msg: str, org: dict, theme: str) -> PageResponse:
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
        org: dict,
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
        org: dict,
        theme: str,
        error: str | None = None,
        values: dict | None = None,
    ) -> PageResponse:
        bank_accounts = self._repo.list_active_bank_accounts()
        return self._render(
            "reconciliation_new.html",
            org=org,
            theme=theme,
            page_key="reconciliations",
            heading="New Bank Reconciliation",
            bank_accounts=bank_accounts,
            error=error,
            values=values or {},
        )

    def handle_new(
        self,
        form_data: dict,
        org: dict,
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
        )
        return f"/reconciliations/{recon_id}", None

    # ── Working screen ─────────────────────────────────────────────────

    def render_working(
        self,
        reconciliation_id: int,
        org: dict,
        theme: str,
        show_prior: bool = False,
        flash_message: str | None = None,
    ) -> PageResponse:
        recon = self._repo.get_reconciliation(reconciliation_id)
        if not recon:
            return self._render_404("Reconciliation not found.", org, theme)

        rows = self._repo.get_working_lines(reconciliation_id)
        summary = self._repo.get_balance_summary(reconciliation_id)

        is_open = recon["status"] == "OPEN"

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
        )

    # ── Toggle (AJAX) ──────────────────────────────────────────────────

    def handle_toggle(
        self,
        reconciliation_id: int,
        form_data: dict,
    ) -> tuple[int, str]:
        """Toggle a JE line's cleared state.  Returns (http_status, json_body)."""
        recon = self._repo.get_reconciliation(reconciliation_id)
        if not recon:
            return 404, json.dumps({"error": "Not found"})
        if recon["status"] != "OPEN":
            return 400, json.dumps({"error": "Reconciliation is not open"})

        line_id_raw = form_data.get("line_id", "")
        if not str(line_id_raw).isdigit():
            return 400, json.dumps({"error": "Invalid line_id"})
        line_id = int(line_id_raw)

        cleared = form_data.get("cleared") in ("1", "true", True)
        if cleared:
            self._repo.clear_line(reconciliation_id, line_id)
        else:
            self._repo.unclear_line(reconciliation_id, line_id)

        summary = self._repo.get_balance_summary(reconciliation_id)
        return 200, json.dumps(summary)

    # ── Finalize ───────────────────────────────────────────────────────

    def handle_finalize(
        self,
        reconciliation_id: int,
        org: dict,
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
            reconciliation_id, summary["book_balance"]
        )
        return (
            f"/reconciliations?msg=Reconciliation+completed+successfully.",
            None,
        )

    # ── Reopen ─────────────────────────────────────────────────────────

    def handle_reopen(
        self,
        reconciliation_id: int,
        org: dict,
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
        org: dict,
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

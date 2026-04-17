"""Manual journal entry pages.

Routes handled:
  GET  /journal-entries              — list all MANUAL journal entries
  GET  /journal-entries/new          — blank entry form (≥2 line rows)
  POST /journal-entries/new          — validate + post entry
  GET  /journal-entries/<id>         — view a posted entry (read-only)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.exceptions import (
    AccountingError,
    ClosedPeriodError,
    ValidationError,
)
from hoa_accounting.models.dto import JournalLineInput
from hoa_accounting.models.enums import SourceType
from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template

_BASE_CTX = {
    "active_nav": "transactions",
    "page_key": "journal-entries",
    "breadcrumb": "Transactions",
}

_MIN_LINES = 2
_MAX_LINES = 30


@dataclass(frozen=True)
class JournalPageResponse:
    status_code: int
    body_html: str


class ManualJournalPages:
    """Render and handle the manual journal entry pages."""

    LIST_TEMPLATE = "journal_entries_list.html"
    FORM_TEMPLATE = "journal_entry_form.html"
    VIEW_TEMPLATE = "journal_entry_view.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.journal_repo = JournalRepository(conn)
        self.accounts_repo = AccountsRepository(conn)

    # ── helpers ───────────────────────────────────────────────────────

    def _account_options(self) -> list[dict]:
        rows = self.accounts_repo.list_chart(active_only=True)
        return [
            {
                "id": r["id"],
                "account_number": r["account_number"],
                "account_name": r["account_name"],
                "fund_code": r["fund_code"],
                "account_type_code": r["account_type_code"],
                "label": f"{r['account_number']} – {r['account_name']}",
            }
            for r in rows
        ]

    def _parse_lines(self, form_data: dict[str, str]) -> list[JournalLineInput]:
        """Parse indexed line fields from the form into JournalLineInput objects.

        Fields are named: account_id_N, description_N, debit_N, credit_N
        where N goes from 1 to line_count.
        """
        try:
            line_count = int(form_data.get("line_count", "0"))
        except ValueError:
            line_count = 0

        lines: list[JournalLineInput] = []
        for i in range(1, line_count + 1):
            account_id_raw = (form_data.get(f"account_id_{i}") or "").strip()
            description = (form_data.get(f"description_{i}") or "").strip()
            debit_raw = (form_data.get(f"debit_{i}") or "").strip()
            credit_raw = (form_data.get(f"credit_{i}") or "").strip()

            # Skip completely blank rows
            if not account_id_raw and not debit_raw and not credit_raw:
                continue

            if not account_id_raw:
                raise ValidationError(f"Line {i}: Account is required.")

            try:
                account_id = int(account_id_raw)
            except ValueError:
                raise ValidationError(f"Line {i}: Invalid account.")

            debit_dec = Decimal("0")
            credit_dec = Decimal("0")
            if debit_raw:
                try:
                    debit_dec = Decimal(debit_raw)
                except InvalidOperation:
                    raise ValidationError(f"Line {i}: Invalid debit amount.")
                if debit_dec < 0:
                    raise ValidationError(f"Line {i}: Debit cannot be negative.")
            if credit_raw:
                try:
                    credit_dec = Decimal(credit_raw)
                except InvalidOperation:
                    raise ValidationError(f"Line {i}: Invalid credit amount.")
                if credit_dec < 0:
                    raise ValidationError(f"Line {i}: Credit cannot be negative.")

            if debit_dec > 0 and credit_dec > 0:
                raise ValidationError(
                    f"Line {i}: Enter either a debit or a credit, not both."
                )

            lines.append(
                JournalLineInput(
                    account_id=account_id,
                    description=description,
                    debit_amount=debit_dec,
                    credit_amount=credit_dec,
                )
            )
        return lines

    def _empty_form_lines(self, count: int = 2) -> list[dict]:
        return [
            {"account_id": "", "description": "", "debit": "", "credit": ""}
            for _ in range(count)
        ]

    def _form_lines_from_data(
        self, form_data: dict[str, str]
    ) -> list[dict]:
        try:
            line_count = int(form_data.get("line_count", "0"))
        except ValueError:
            line_count = 0
        rows = []
        for i in range(1, line_count + 1):
            rows.append({
                "account_id": form_data.get(f"account_id_{i}", ""),
                "description": form_data.get(f"description_{i}", ""),
                "debit": form_data.get(f"debit_{i}", ""),
                "credit": form_data.get(f"credit_{i}", ""),
            })
        if len(rows) < _MIN_LINES:
            rows.extend(self._empty_form_lines(_MIN_LINES - len(rows)))
        return rows

    # ── list ──────────────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> JournalPageResponse:
        rows = self.journal_repo.list_manual_entries()
        entries = [dict(r) for r in rows]
        ctx = {
            **_BASE_CTX,
            "heading": "Manual Journal Entries",
            "org": org or {},
            "theme": theme,
            "entries": entries,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return JournalPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── new entry form (GET) ───────────────────────────────────────────

    def render_new_form(
        self,
        *,
        org: dict | None,
        theme: str,
        form_data: dict[str, str] | None = None,
        error_message: str = "",
    ) -> JournalPageResponse:
        if form_data:
            lines = self._form_lines_from_data(form_data)
            values = {
                "entry_date": form_data.get("entry_date", ""),
                "memo": form_data.get("memo", ""),
            }
        else:
            lines = self._empty_form_lines(2)
            values = {"entry_date": "", "memo": ""}

        ctx = {
            **_BASE_CTX,
            "heading": "New Manual Journal Entry",
            "breadcrumb": "Transactions · Manual Journal Entries",
            "org": org or {},
            "theme": theme,
            "values": values,
            "lines": lines,
            "account_options": self._account_options(),
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return JournalPageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── new entry (POST) ──────────────────────────────────────────────

    def handle_new(
        self,
        *,
        form_data: dict[str, str],
        org: dict | None,
        theme: str,
    ) -> tuple[str | None, JournalPageResponse | None]:
        def _err(msg: str) -> tuple[None, JournalPageResponse]:
            return None, self.render_new_form(
                org=org, theme=theme,
                form_data=form_data,
                error_message=msg,
            )

        entry_date = (form_data.get("entry_date") or "").strip()
        memo = (form_data.get("memo") or "").strip()

        if not entry_date:
            return _err("Entry Date is required.")
        if not memo:
            return _err("Memo is required.")

        try:
            lines = self._parse_lines(form_data)
        except ValidationError as exc:
            return _err(str(exc))

        if len(lines) < _MIN_LINES:
            return _err(f"At least {_MIN_LINES} non-blank lines are required.")

        factory = ServiceFactory(self.conn)
        svc = factory.journal_service()
        try:
            result = svc.post_journal_entry(
                entry_date=entry_date,
                source_type=SourceType.MANUAL.value,
                memo=memo,
                lines=lines,
                created_by_user_id=None,
                inter_fund_allowed=True,
            )
            self.conn.commit()
        except AccountingError as exc:
            return _err(str(exc))
        except Exception:
            self.conn.rollback()
            raise

        return (
            f"/journal-entries/{result.journal_entry_id}"
            f"?msg=Entry+{result.entry_number}+posted.",
            None,
        )

    # ── view entry (GET) ──────────────────────────────────────────────

    def render_view(
        self,
        *,
        journal_entry_id: int,
        org: dict | None,
        theme: str,
        flash_message: str = "",
    ) -> JournalPageResponse:
        header, lines = self.journal_repo.get_journal_entry_with_lines(
            journal_entry_id
        )
        if header is None:
            ctx = {
                **_BASE_CTX,
                "heading": "Journal Entry Not Found",
                "org": org or {},
                "theme": theme,
                "error_message": f"Journal entry #{journal_entry_id} not found.",
                "entries": [],
                "flash_message": "",
            }
            return JournalPageResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body_html=render_template(self.LIST_TEMPLATE, ctx),
            )

        total_debits = sum(
            Decimal(str(ln["debit_amount"])) for ln in lines
        )
        total_credits = sum(
            Decimal(str(ln["credit_amount"])) for ln in lines
        )

        ctx = {
            **_BASE_CTX,
            "heading": f"Journal Entry {dict(header)['entry_number']}",
            "breadcrumb": "Transactions · Manual Journal Entries",
            "org": org or {},
            "theme": theme,
            "entry": dict(header),
            "lines": [dict(ln) for ln in lines],
            "total_debits": str(total_debits),
            "total_credits": str(total_credits),
            "flash_message": flash_message,
        }
        return JournalPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.VIEW_TEMPLATE, ctx),
        )

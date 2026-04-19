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

# ── Common adjustment templates shown in the "Quick Start" dropdown ────────────
# Each template defines:
#   name        – shown in the select
#   description – shown as a helper subtitle when selected
#   memo        – pre-fills the Memo field
#   lines       – list of line stubs:
#       side          "debit" | "credit"
#       account_match {"by": "number"|"type", "value": "1100"|"EXPENSE"}
#                     first match in the accounts list wins; blank if none found
#       hint          shown to the user if no account auto-matched
#
# account_match is resolved client-side in JavaScript so it works regardless of
# which chart of accounts a specific HOA has configured.

_ADJUSTMENT_TEMPLATES: list[dict] = [
    {
        "id": "blank",
        "name": "— What do you need to do? —",
        "plain_english": "",
        "description": "",
        "flow": [],
        "memo": "",
        "lines": [],
    },
    # ── Common corrections ─────────────────────────────────────────────────
    {
        "id": "expense_reclassify",
        "name": "I paid a bill to the wrong expense category",
        "plain_english": (
            "Moves an expense from the wrong category to the right one. "
            "No money changes hands — only the category label changes."
        ),
        "description": (
            "Example: you posted the pool repair bill to Landscaping by mistake. "
            "This entry moves it to Pool & Spa. Pick the CORRECT category first, "
            "then the WRONG one."
        ),
        "flow": [
            {"label": "Correct expense account", "side": "DEBIT", "note": "increases"},
            {"label": "Wrong expense account", "side": "CREDIT", "note": "decreases"},
        ],
        "memo": "Expense reclassification — correct category",
        "lines": [
            {
                "side": "debit",
                "account_match": {"by": "type", "value": "EXPENSE"},
                "hint": "CORRECT expense account (where it should have gone)",
            },
            {
                "side": "credit",
                "account_match": {"by": "type", "value": "EXPENSE"},
                "hint": "WRONG expense account (where it was posted by mistake)",
            },
        ],
    },
    {
        "id": "write_off_owner",
        "name": "I need to write off an owner who will never pay",
        "plain_english": (
            "Removes the uncollectible balance from your books so your records "
            "don't show money you'll never actually receive."
        ),
        "description": (
            "Example: an owner moved away and left a $620 balance you've been "
            "unable to collect. This clears the balance from Dues Receivable and "
            "records it as a bad-debt expense."
        ),
        "flow": [
            {"label": "Bad Debt / Write-Off Expense", "side": "DEBIT", "note": "records the loss"},
            {"label": "Dues Receivable", "side": "CREDIT", "note": "clears the balance"},
        ],
        "memo": "Write off uncollectible owner balance",
        "lines": [
            {
                "side": "debit",
                "account_match": {"by": "type", "value": "EXPENSE"},
                "hint": "Bad Debt Expense or Write-Off Expense account",
            },
            {
                "side": "credit",
                "account_match": {"by": "number", "value": "1100"},
                "hint": "Dues Receivable (usually account 1100)",
            },
        ],
    },
    {
        "id": "waive_late_fee",
        "name": "I need to waive a late fee for an owner",
        "plain_english": (
            "Forgives a late fee that was already charged. The board voted to "
            "waive it, so you need to reverse the income and reduce what the owner owes."
        ),
        "description": (
            "Example: the board approved waiving a $25 late fee for an owner "
            "who paid late due to a medical emergency. This reverses the fee."
        ),
        "flow": [
            {"label": "Late Fee Income", "side": "DEBIT", "note": "reverses the fee"},
            {"label": "Dues Receivable", "side": "CREDIT", "note": "reduces what owner owes"},
        ],
        "memo": "Late fee waiver — board approved",
        "lines": [
            {
                "side": "debit",
                "account_match": {"by": "number", "value": "4100"},
                "hint": "Late Fee Income account (usually 4100)",
            },
            {
                "side": "credit",
                "account_match": {"by": "number", "value": "1100"},
                "hint": "Dues Receivable (usually account 1100)",
            },
        ],
    },
    {
        "id": "refund_homeowner",
        "name": "I need to refund money to a homeowner",
        "plain_english": (
            "Records a refund check written to an owner who overpaid or was "
            "charged incorrectly. Money leaves your checking account."
        ),
        "description": (
            "Example: an owner paid their dues twice by accident. You wrote them "
            "a refund check. This records that the receivable went up (since they "
            "now owe less net) and cash went down."
        ),
        "flow": [
            {"label": "Dues Receivable", "side": "DEBIT", "note": "reduces credit on account"},
            {"label": "Operating Checking", "side": "CREDIT", "note": "money leaves the bank"},
        ],
        "memo": "Homeowner refund",
        "lines": [
            {
                "side": "debit",
                "account_match": {"by": "number", "value": "1100"},
                "hint": "Dues Receivable (usually account 1100)",
            },
            {
                "side": "credit",
                "account_match": {"by": "number", "value": "1000"},
                "hint": "Operating Checking / Cash (usually account 1000)",
            },
        ],
    },
    # ── Recording income & bank items ──────────────────────────────────────
    {
        "id": "bank_interest",
        "name": "I need to record interest we earned at the bank",
        "plain_english": (
            "Your bank statement shows interest deposited but it's not in the "
            "books yet. This adds it to both your cash balance and income."
        ),
        "description": (
            "Example: the bank credited $42.18 interest to your operating account. "
            "Enter that amount as a debit to Cash and a credit to Interest Income."
        ),
        "flow": [
            {"label": "Operating Checking", "side": "DEBIT", "note": "cash goes up"},
            {"label": "Interest Income", "side": "CREDIT", "note": "income goes up"},
        ],
        "memo": "Bank interest earned",
        "lines": [
            {
                "side": "debit",
                "account_match": {"by": "number", "value": "1000"},
                "hint": "Operating Checking / Cash (usually account 1000)",
            },
            {
                "side": "credit",
                "account_match": {"by": "number", "value": "4200"},
                "hint": "Interest Income (usually account 4200)",
            },
        ],
    },
    {
        "id": "bank_fee",
        "name": "I need to record a bank fee or service charge",
        "plain_english": (
            "Your bank statement shows a fee that wasn't entered as a bill. "
            "This records the expense and reduces your cash balance."
        ),
        "description": (
            "Example: the bank charged a $15 monthly service fee or an NSF fee. "
            "Debit Bank Service Charges expense and credit Operating Cash."
        ),
        "flow": [
            {"label": "Bank Service Charges (Expense)", "side": "DEBIT", "note": "expense goes up"},
            {"label": "Operating Checking", "side": "CREDIT", "note": "cash goes down"},
        ],
        "memo": "Bank service fee",
        "lines": [
            {
                "side": "debit",
                "account_match": {"by": "type", "value": "EXPENSE"},
                "hint": "Bank Service Charges or Bank Fees expense account",
            },
            {
                "side": "credit",
                "account_match": {"by": "number", "value": "1000"},
                "hint": "Operating Checking / Cash (usually account 1000)",
            },
        ],
    },
    {
        "id": "income_tax_payment",
        "name": "I need to record income tax paid on interest earned",
        "plain_english": (
            "The HOA owed tax on interest income and you wrote a check to the IRS "
            "or state. This records that payment as an expense."
        ),
        "description": (
            "Example: you mailed a $78 check to the IRS for Form 1120-H taxes "
            "on reserve interest. Debit Income Tax Expense and credit Cash."
        ),
        "flow": [
            {"label": "Income Tax Expense", "side": "DEBIT", "note": "expense goes up"},
            {"label": "Operating Checking", "side": "CREDIT", "note": "cash goes down"},
        ],
        "memo": "Income tax payment — interest earned",
        "lines": [
            {
                "side": "debit",
                "account_match": {"by": "type", "value": "EXPENSE"},
                "hint": "Income Tax Expense account",
            },
            {
                "side": "credit",
                "account_match": {"by": "number", "value": "1000"},
                "hint": "Operating Checking / Cash (usually account 1000)",
            },
        ],
    },
    # ── Reserve fund ───────────────────────────────────────────────────────
    {
        "id": "reserve_project",
        "name": "I need to record a payment for a reserve project",
        "plain_english": (
            "Money was paid from the Reserve savings account for a planned "
            "capital project (roof, pavement, pool, etc.)."
        ),
        "description": (
            "Example: you paid a roofer $8,400 from the Reserve account. "
            "Debit Reserve Expense and credit Reserve Cash/Savings."
        ),
        "flow": [
            {"label": "Reserve Expense", "side": "DEBIT", "note": "expense goes up"},
            {"label": "Reserve Savings / Cash", "side": "CREDIT", "note": "reserve cash goes down"},
        ],
        "memo": "Reserve fund project payment",
        "lines": [
            {
                "side": "debit",
                "account_match": {"by": "number", "value": "6100"},
                "hint": "Reserve Expense (usually account 6100)",
            },
            {
                "side": "credit",
                "account_match": {"by": "number", "value": "1010"},
                "hint": "Reserve Savings / Cash (usually account 1010)",
            },
        ],
    },
    # ── Month-end adjustments ──────────────────────────────────────────────
    {
        "id": "accrue_expense",
        "name": "I know we owe money for a bill that hasn't arrived yet",
        "plain_english": (
            "Records an expense in the correct month even though the vendor "
            "hasn't sent the invoice yet. You'll enter the actual bill later."
        ),
        "description": (
            "Example: it's December 31 and you haven't received the December "
            "landscaping invoice yet, but the service was done. Debit the expense "
            "and credit Accounts Payable to record it in December."
        ),
        "flow": [
            {"label": "Expense account", "side": "DEBIT", "note": "expense in right month"},
            {"label": "Accounts Payable", "side": "CREDIT", "note": "we owe this amount"},
        ],
        "memo": "Accrued expense — bill not yet received",
        "lines": [
            {
                "side": "debit",
                "account_match": {"by": "type", "value": "EXPENSE"},
                "hint": "The applicable expense account (landscaping, utilities, etc.)",
            },
            {
                "side": "credit",
                "account_match": {"by": "type", "value": "LIABILITY"},
                "hint": "Accounts Payable or Accrued Liabilities",
            },
        ],
    },
    {
        "id": "prepaid_expense",
        "name": "I prepaid something that covers several future months",
        "plain_english": (
            "You paid the full amount upfront (like annual insurance) but the "
            "expense should be spread across future months, not all at once."
        ),
        "description": (
            "Example: you paid $1,200 for the year's insurance policy in January. "
            "Debit Prepaid Insurance (an asset) so you can expense $100/month "
            "going forward. Credit Cash since money left the bank."
        ),
        "flow": [
            {"label": "Prepaid Expenses (Asset)", "side": "DEBIT", "note": "asset goes up"},
            {"label": "Operating Checking", "side": "CREDIT", "note": "cash goes down"},
        ],
        "memo": "Prepaid expense — spread over future months",
        "lines": [
            {
                "side": "debit",
                "account_match": {"by": "type", "value": "ASSET"},
                "hint": "Prepaid Expenses or Prepaid Insurance (an Asset account)",
            },
            {
                "side": "credit",
                "account_match": {"by": "number", "value": "1000"},
                "hint": "Operating Checking / Cash (usually account 1000)",
            },
        ],
    },
]


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
            "adjustment_templates": _ADJUSTMENT_TEMPLATES,
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

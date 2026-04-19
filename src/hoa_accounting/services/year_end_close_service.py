"""Year-End Close service.

Orchestrates the three-step close workflow:
  1. Pre-close checklist   — all periods closed, no draft entries
  2. Closing journal entry — zero income/expense into Fund Balance (per fund)
  3. Fiscal-year lock      — record in fiscal_year_closes

A formal close can be re-opened for corrections.  Re-opening reverses the
closing entries and stamps reopened_at; it does NOT automatically reopen
individual accounting periods (the user controls that separately).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import AccountingError, ValidationError
from hoa_accounting.models.dto import JournalLineInput
from hoa_accounting.models.enums import SourceType
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.repositories.year_end_close_repo import YearEndCloseRepository
from hoa_accounting.validators.common import q2


# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class ChecklistItem:
    label: str
    passed: bool
    detail: str = ""        # extra info shown in the UI


@dataclass
class FundSummary:
    fund_code: str
    total_income: Decimal
    total_expense: Decimal

    @property
    def net_income(self) -> Decimal:
        return self.total_income - self.total_expense


@dataclass
class CloseChecklist:
    fiscal_year: int
    items: list[ChecklistItem] = field(default_factory=list)
    fund_summaries: list[FundSummary] = field(default_factory=list)

    @property
    def can_close(self) -> bool:
        return all(item.passed for item in self.items)


@dataclass(frozen=True)
class CloseResult:
    fiscal_year: int
    je_operating_number: Optional[str]
    je_reserve_number: Optional[str]


@dataclass(frozen=True)
class ReopenResult:
    fiscal_year: int


# ── Service ────────────────────────────────────────────────────────────────────

class YearEndCloseService:
    """Owns the year-end close and reopen workflows."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        close_repo: YearEndCloseRepository,
        journal_repo: JournalRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.conn = conn
        self.close_repo = close_repo
        self.journal_repo = journal_repo
        self.audit_repo = audit_repo

    # ── Checklist ─────────────────────────────────────────────────────────

    def build_checklist(self, fiscal_year: int) -> CloseChecklist:
        """Build the pre-close checklist for a fiscal year (read-only)."""
        cl = CloseChecklist(fiscal_year=fiscal_year)

        # 1. The year must not already be closed.
        already_closed = self.close_repo.is_fiscal_year_closed(fiscal_year)
        if already_closed:
            cl.items.append(ChecklistItem(
                label="Fiscal year not already closed",
                passed=False,
                detail="This year has already been formally closed. Re-open it first.",
            ))
            return cl  # nothing else to check

        # 2. All accounting periods must be closed.
        open_periods = self.close_repo.get_open_periods(fiscal_year)
        if open_periods:
            names = ", ".join(str(r["period_name"]) for r in open_periods)
            cl.items.append(ChecklistItem(
                label="All periods are closed",
                passed=False,
                detail=f"Open periods: {names}",
            ))
        else:
            cl.items.append(ChecklistItem(
                label="All periods are closed",
                passed=True,
            ))

        # 3. No DRAFT journal entries.
        draft_count = self.close_repo.get_draft_entries(fiscal_year)
        if draft_count:
            cl.items.append(ChecklistItem(
                label="No draft journal entries",
                passed=False,
                detail=f"{draft_count} draft entry/entries must be posted or deleted.",
            ))
        else:
            cl.items.append(ChecklistItem(
                label="No draft journal entries",
                passed=True,
            ))

        # 4. Fund Balance accounts exist for each fund with activity.
        balances = self.close_repo.get_income_expense_balances(fiscal_year)
        funds_with_activity = {str(r["fund_code"]) for r in balances}
        missing_fb: list[str] = []
        for fund_code in funds_with_activity:
            if not self.close_repo.get_fund_balance_account(fund_code):
                missing_fb.append(fund_code)
        if missing_fb:
            cl.items.append(ChecklistItem(
                label="Fund Balance accounts exist",
                passed=False,
                detail=f"No equity account for fund(s): {', '.join(missing_fb)}",
            ))
        else:
            cl.items.append(ChecklistItem(
                label="Fund Balance accounts exist",
                passed=True,
            ))

        # Compute fund summaries for the preview section.
        cl.fund_summaries = self._compute_fund_summaries(balances)
        return cl

    # ── Close ──────────────────────────────────────────────────────────────

    def close_year(self, fiscal_year: int) -> CloseResult:
        """
        Execute the year-end close:
          • Verify the checklist passes.
          • Post one closing JE per fund that had income/expense activity.
          • Record the close in fiscal_year_closes.
        """
        cl = self.build_checklist(fiscal_year)
        if not cl.can_close:
            failed = [i.label for i in cl.items if not i.passed]
            raise ValidationError(
                f"Cannot close fiscal year {fiscal_year}. "
                f"Failed checks: {'; '.join(failed)}"
            )

        entry_date = self.close_repo.get_last_period_end_date(fiscal_year)
        if not entry_date:
            raise ValidationError(
                f"No accounting periods found for fiscal year {fiscal_year}."
            )

        period_id = self.close_repo.get_last_period_id(fiscal_year)
        if not period_id:
            raise ValidationError(
                f"Cannot find last period id for fiscal year {fiscal_year}."
            )

        balances = self.close_repo.get_income_expense_balances(fiscal_year)
        now = _now_utc()

        with transaction(self.conn):
            je_op_id: int | None = None
            je_op_num: str | None = None
            je_rv_id: int | None = None
            je_rv_num: str | None = None

            for fund_code in ("OPERATING", "RESERVE"):
                fund_balances = [r for r in balances if str(r["fund_code"]) == fund_code]
                if not fund_balances:
                    continue

                fb_account = self.close_repo.get_fund_balance_account(fund_code)
                if not fb_account:
                    raise AccountingError(
                        f"No Fund Balance equity account found for fund {fund_code}."
                    )

                lines, net_income = self._build_closing_lines(
                    fund_balances, int(fb_account["id"]), fund_code
                )
                if not lines:
                    continue

                fund_label = "Operating" if fund_code == "OPERATING" else "Reserve"
                net_label = (
                    f"net income ${net_income:,.2f}"
                    if net_income >= 0
                    else f"net loss $({abs(net_income):,.2f})"
                )
                memo = (
                    f"Year-End Close {fiscal_year} — {fund_label} Fund "
                    f"({net_label} to Fund Balance)"
                )

                # Post directly to the last period — bypasses PeriodValidator
                # intentionally (all periods are closed by design at this point).
                je_id, je_num = self.journal_repo.insert_journal_entry_with_generated_number(
                    entry_date=entry_date,
                    accounting_period_id=period_id,
                    source_type=SourceType.YEAR_END_CLOSE,
                    memo=memo,
                    created_by_user_id=None,
                )
                self.journal_repo.insert_journal_lines(
                    journal_entry_id=je_id,
                    lines=lines,
                    amount_formatter=q2,
                )
                self.audit_repo.write(
                    entity_type="journal_entries",
                    entity_id=je_id,
                    action="YEAR_END_CLOSE",
                    user_id=None,
                    after_json={
                        "entry_number": je_num,
                        "fiscal_year": fiscal_year,
                        "fund_code": fund_code,
                        "net_income": str(net_income),
                    },
                )

                if fund_code == "OPERATING":
                    je_op_id, je_op_num = je_id, je_num
                else:
                    je_rv_id, je_rv_num = je_id, je_num

            self.close_repo.insert_close(
                fiscal_year=fiscal_year,
                closed_at=now,
                closing_je_operating_id=je_op_id,
                closing_je_reserve_id=je_rv_id,
            )

        return CloseResult(
            fiscal_year=fiscal_year,
            je_operating_number=je_op_num,
            je_reserve_number=je_rv_num,
        )

    # ── Reopen ────────────────────────────────────────────────────────────

    def reopen_year(self, fiscal_year: int) -> ReopenResult:
        """
        Re-open a formally closed fiscal year:
          • Reverse the closing journal entries (swap DR/CR).
          • Mark the close record as reopened.
        Individual accounting periods are NOT automatically reopened —
        the user must reopen them manually to post new entries.
        """
        record = self.close_repo.get_close_record(fiscal_year)
        if not record or record["reopened_at"] is not None:
            raise ValidationError(
                f"Fiscal year {fiscal_year} is not currently closed."
            )

        entry_date = self.close_repo.get_last_period_end_date(fiscal_year)
        period_id  = self.close_repo.get_last_period_id(fiscal_year)
        now = _now_utc()

        with transaction(self.conn):
            for (je_id_col, fund_label) in (
                ("closing_je_operating_id", "Operating"),
                ("closing_je_reserve_id",   "Reserve"),
            ):
                original_je_id = record[je_id_col]
                if not original_je_id:
                    continue

                # Read original lines and swap DR/CR.
                original_lines = list(self.conn.execute(
                    """
                    SELECT account_id, description,
                           debit_amount, credit_amount
                    FROM journal_entry_lines
                    WHERE journal_entry_id = ?
                    ORDER BY line_number
                    """,
                    (original_je_id,),
                ).fetchall())

                reversal_lines = [
                    JournalLineInput(
                        account_id=int(row["account_id"]),
                        description=f"Reversal: {row['description']}",
                        debit_amount=Decimal(str(row["credit_amount"])),
                        credit_amount=Decimal(str(row["debit_amount"])),
                    )
                    for row in original_lines
                ]

                rev_je_id, rev_je_num = (
                    self.journal_repo.insert_journal_entry_with_generated_number(
                        entry_date=entry_date,
                        accounting_period_id=period_id,
                        source_type=SourceType.REVERSAL,
                        memo=f"Reversal of Year-End Close {fiscal_year} — {fund_label} Fund",
                        created_by_user_id=None,
                    )
                )
                self.journal_repo.insert_journal_lines(
                    journal_entry_id=rev_je_id,
                    lines=reversal_lines,
                    amount_formatter=q2,
                )

                # Mark the original JE as reversed.
                self.conn.execute(
                    "UPDATE journal_entries SET status='REVERSED', reversal_entry_id=? WHERE id=?",
                    (rev_je_id, original_je_id),
                )

                self.audit_repo.write(
                    entity_type="journal_entries",
                    entity_id=rev_je_id,
                    action="YEAR_END_REOPEN",
                    user_id=None,
                    after_json={
                        "reverses_je_id": original_je_id,
                        "fiscal_year": fiscal_year,
                        "fund": fund_label,
                    },
                )

            self.close_repo.mark_reopened(fiscal_year, now)

        return ReopenResult(fiscal_year=fiscal_year)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _compute_fund_summaries(
        self, balances: list[sqlite3.Row]
    ) -> list[FundSummary]:
        funds: dict[str, FundSummary] = {}
        for row in balances:
            fc   = str(row["fund_code"])
            atyp = str(row["account_type"])
            amt  = Decimal(str(row["net_balance"]))
            if fc not in funds:
                funds[fc] = FundSummary(
                    fund_code=fc,
                    total_income=Decimal("0"),
                    total_expense=Decimal("0"),
                )
            if atyp == "INCOME":
                funds[fc].total_income += amt
            else:
                funds[fc].total_expense += amt
        return list(funds.values())

    def _build_closing_lines(
        self,
        fund_balances: list[sqlite3.Row],
        fb_account_id: int,
        fund_code: str,
    ) -> tuple[list[JournalLineInput], Decimal]:
        """
        Build the JE lines that zero out income/expense into Fund Balance.

        Returns (lines, net_income).  net_income is positive for a profit,
        negative for a loss.
        """
        lines: list[JournalLineInput] = []
        total_income  = Decimal("0")
        total_expense = Decimal("0")

        for row in fund_balances:
            atyp    = str(row["account_type"])
            acct_id = int(row["account_id"])
            balance = Decimal(str(row["net_balance"]))
            name    = str(row["account_name"])

            if balance <= 0:
                continue  # skip accounts with no net activity

            if atyp == "INCOME":
                # INCOME normal balance = CREDIT → debit to close
                lines.append(JournalLineInput(
                    account_id=acct_id,
                    description=f"Close {name}",
                    debit_amount=balance,
                    credit_amount=Decimal("0"),
                ))
                total_income += balance

            elif atyp == "EXPENSE":
                # EXPENSE normal balance = DEBIT → credit to close
                lines.append(JournalLineInput(
                    account_id=acct_id,
                    description=f"Close {name}",
                    debit_amount=Decimal("0"),
                    credit_amount=balance,
                ))
                total_expense += balance

        net_income = total_income - total_expense
        if not lines:
            return [], net_income

        # Fund Balance line — credit for profit, debit for loss.
        fb_label = f"Year-End Net {'Income' if net_income >= 0 else 'Loss'} {fund_code.capitalize()}"
        if net_income >= 0:
            lines.append(JournalLineInput(
                account_id=fb_account_id,
                description=fb_label,
                debit_amount=Decimal("0"),
                credit_amount=net_income,
            ))
        else:
            lines.append(JournalLineInput(
                account_id=fb_account_id,
                description=fb_label,
                debit_amount=abs(net_income),
                credit_amount=Decimal("0"),
            ))

        return lines, net_income


# ── Utilities ──────────────────────────────────────────────────────────────────

def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

"""Page-service for the consolidated Opening Balances screen."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from hoa_accounting.exceptions import ClosedPeriodError, ValidationError
from hoa_accounting.models.dto import JournalLineInput
from hoa_accounting.models.enums import SourceType
from hoa_accounting.repositories.opening_balances_repo import OpeningBalancesRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


class OpeningBalancesPages:
    """Render and handle the Opening Balances entry screen."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        ar_account_number: str = "1100",
    ) -> None:
        self._conn = conn
        self._repo = OpeningBalancesRepository(conn)
        self._factory = ServiceFactory(conn)
        self._ar_account_number = ar_account_number

    # ── Helpers ────────────────────────────────────────────────────────

    def _render(self, template: str, **ctx) -> PageResponse:
        return PageResponse(200, render_template(template, ctx))

    def _page_ctx(
        self,
        *,
        org: dict,
        theme: str,
        error: str | None = None,
        flash: str | None = None,
        values: dict | None = None,
        as_of_date: str = "",
        bank_rows: list | None = None,
        lot_rows: list | None = None,
        has_existing_je: bool = False,
    ) -> PageResponse:
        bank_rows = bank_rows if bank_rows is not None else self._repo.get_bank_accounts_with_balances()
        lot_rows = lot_rows if lot_rows is not None else self._repo.get_lots_with_balances()
        return self._render(
            "opening_balances.html",
            org=org, theme=theme,
            page_key="opening-balances",
            heading="Opening Balances",
            bank_rows=bank_rows,
            lot_rows=lot_rows,
            has_existing_je=has_existing_je,
            as_of_date=as_of_date,
            values=values or {},
            error=error,
            flash=flash,
        )

    # ── Render ─────────────────────────────────────────────────────────

    def render_page(
        self,
        org: dict,
        theme: str,
        flash: str | None = None,
        error: str | None = None,
    ) -> PageResponse:
        bank_rows = self._repo.get_bank_accounts_with_balances()
        lot_rows = self._repo.get_lots_with_balances()
        has_existing_je = self._repo.get_current_je_id() is not None

        # Pre-fill as_of_date from any existing record
        as_of_date = next(
            (str(r["as_of_date"]) for r in bank_rows if r["as_of_date"]),
            next(
                (str(r["as_of_date"]) for r in lot_rows if r["as_of_date"]),
                "",
            ),
        )

        return self._page_ctx(
            org=org, theme=theme,
            flash=flash, error=error,
            as_of_date=as_of_date,
            bank_rows=bank_rows,
            lot_rows=lot_rows,
            has_existing_je=has_existing_je,
        )

    # ── Save ───────────────────────────────────────────────────────────

    def handle_save(
        self,
        form_data: dict,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        as_of_date = form_data.get("as_of_date", "").strip()

        def _err(msg: str) -> tuple[str | None, PageResponse | None]:
            bank_rows = self._repo.get_bank_accounts_with_balances()
            lot_rows = self._repo.get_lots_with_balances()
            has_existing_je = self._repo.get_current_je_id() is not None
            return None, self._page_ctx(
                org=org, theme=theme,
                error=msg,
                values=form_data,
                as_of_date=as_of_date,
                bank_rows=bank_rows,
                lot_rows=lot_rows,
                has_existing_je=has_existing_je,
            )

        if not as_of_date:
            return _err("As of date is required.")

        # ── Parse bank amounts ─────────────────────────────────────────
        bank_rows = self._repo.get_bank_accounts_with_balances()
        bank_amounts: dict[int, tuple[int, Decimal]] = {}  # bank_id → (gl_id, amt)
        for row in bank_rows:
            bid = int(row["bank_account_id"])
            raw = form_data.get(f"bank_{bid}", "0").strip().replace(",", "") or "0"
            try:
                amt = Decimal(raw)
            except InvalidOperation:
                return _err(f"Invalid amount for bank account {row['account_name']}.")
            if amt < 0:
                return _err(f"Amount for {row['account_name']} cannot be negative.")
            if amt > 0:
                bank_amounts[bid] = (int(row["gl_account_id"]), amt)

        # ── Parse lot amounts ──────────────────────────────────────────
        lot_rows = self._repo.get_lots_with_balances()
        lot_amounts: dict[int, Decimal] = {}
        for row in lot_rows:
            lid = int(row["lot_id"])
            raw = form_data.get(f"lot_{lid}", "0").strip().replace(",", "") or "0"
            try:
                amt = Decimal(raw)
            except InvalidOperation:
                return _err(f"Invalid amount for lot {row['lot_number']}.")
            if amt < 0:
                return _err(f"Amount for lot {row['lot_number']} cannot be negative.")
            if amt > 0:
                lot_amounts[lid] = amt

        total_banks = sum(v for _, v in bank_amounts.values())
        total_lots = sum(lot_amounts.values())
        total = total_banks + total_lots

        if total == 0:
            return _err("Enter at least one opening balance before saving.")

        # ── Validate AR account when lot balances exist ────────────────
        ar_acct_id: int | None = None
        if total_lots > 0:
            ar_row = self._conn.execute(
                "SELECT id FROM accounts WHERE account_number = ? AND is_active = 1",
                (self._ar_account_number,),
            ).fetchone()
            if not ar_row:
                return _err(
                    f"AR account {self._ar_account_number!r} not found. "
                    "Check your Chart of Accounts."
                )
            ar_acct_id = int(ar_row["id"])

        try:
            # Delete existing JE if one was previously posted
            existing_je_id = self._repo.get_current_je_id()
            if existing_je_id:
                self._repo.clear_all_je_references()
                self._conn.execute(
                    "DELETE FROM journal_entries WHERE id = ?", (existing_je_id,)
                )

            # Ensure the Opening Balance Offset equity account exists
            offset_id = self._repo.ensure_offset_account()

            # Build JE lines
            lines: list[JournalLineInput] = []
            for _bid, (gl_id, amt) in bank_amounts.items():
                lines.append(
                    JournalLineInput(
                        account_id=gl_id,
                        description="Opening balance",
                        debit_amount=amt,
                    )
                )
            if ar_acct_id is not None:
                lines.append(
                    JournalLineInput(
                        account_id=ar_acct_id,
                        description="Opening balance — owner AR",
                        debit_amount=total_lots,
                    )
                )
            lines.append(
                JournalLineInput(
                    account_id=offset_id,
                    description="Opening balance offset",
                    credit_amount=total,
                )
            )

            # Post the JE
            svc = self._factory.journal_service()
            journal = svc.post_journal_entry(
                entry_date=as_of_date,
                source_type=SourceType.OPENING_BALANCE.value,
                memo="Opening balances",
                created_by_user_id=None,
                inter_fund_allowed=True,
                lines=lines,
            )
            je_id = journal.journal_entry_id

            # Persist opening-balance records
            for bid, (_gl_id, amt) in bank_amounts.items():
                self._repo.upsert_balance("BANK_ACCOUNT", bid, as_of_date, str(amt), je_id)
            for lid, amt in lot_amounts.items():
                self._repo.upsert_balance("LOT", lid, as_of_date, str(amt), je_id)

            self._conn.commit()

        except (ValidationError, ClosedPeriodError) as exc:
            self._conn.rollback()
            return _err(str(exc))
        except Exception:
            self._conn.rollback()
            raise

        return "/opening-balances?msg=Opening+balances+saved.", None

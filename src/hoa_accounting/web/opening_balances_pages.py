"""Page-service for the consolidated Opening Balances screen."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.opening_balances_repo import OpeningBalancesRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


class OpeningBalancesPages:
    """Render and handle the Opening Balances entry screen."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._repo = OpeningBalancesRepository(conn)
        self._factory = ServiceFactory(conn)

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
        bank_amounts: dict[int, tuple[None, Decimal]] = {}  # bank_id → (None, amt) — gl_id retired
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
                bank_amounts[bid] = (None, amt)

        # ── Parse lot amounts (dues + assessment separately) ───────────
        lot_rows = self._repo.get_lots_with_balances()
        lot_dues: dict[int, Decimal] = {}
        lot_assess: dict[int, Decimal] = {}
        for row in lot_rows:
            lid = int(row["lot_id"])
            for field, store in (
                (f"lot_{lid}_dues", lot_dues),
                (f"lot_{lid}_assess", lot_assess),
            ):
                raw = form_data.get(field, "0").strip().replace(",", "") or "0"
                try:
                    amt = Decimal(raw)
                except InvalidOperation:
                    return _err(f"Invalid amount for lot {row['lot_number']}.")
                if amt != 0:
                    store[lid] = amt

        total_banks = sum(v for _, v in bank_amounts.values())
        total_lots = sum(lot_dues.values()) + sum(lot_assess.values())
        total = total_banks + total_lots

        if total == 0 and not lot_dues and not lot_assess:
            return _err("Enter at least one opening balance before saving.")

        # AR account no longer needed — chart of accounts retired.

        try:
            # Cash basis, no GL: opening balances are simple data rows.
            # Persist directly without journal-entry posting.
            for bid, (_gl_id, amt) in bank_amounts.items():
                self._repo.upsert_balance("BANK_ACCOUNT", bid, as_of_date, str(amt))
            for lid, amt in lot_dues.items():
                self._repo.upsert_balance("LOT_DUES", lid, as_of_date, str(amt))
            for lid, amt in lot_assess.items():
                self._repo.upsert_balance("LOT_ASSESSMENT", lid, as_of_date, str(amt))

            self._conn.commit()

        except ValidationError as exc:
            self._conn.rollback()
            return _err(str(exc))
        except Exception:
            self._conn.rollback()
            raise

        return "/opening-balances?msg=Opening+balances+saved.", None

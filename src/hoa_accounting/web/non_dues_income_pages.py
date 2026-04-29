"""Non-dues income list page + batch entry form."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.categories_repo import CategoriesRepository
from hoa_accounting.repositories.income_batches_repo import IncomeBatchesRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.services.non_dues_income_service import IncomeRow
from hoa_accounting.web.template_engine import render_template
from hoa_accounting.validators.format import format_money
from hoa_accounting.validators.forms import parse_int as _parse_int, parse_positive_decimal as _parse_positive_decimal, require as _require


@dataclass(frozen=True)
class IncomePageResponse:
    status_code: int
    body_html: str


_ROW_KEY_RE = re.compile(r"^row_(\d+)_(lot_id|amount|memo)$")


def _today() -> str:
    return _date.today().isoformat()


class NonDuesIncomePages:
    """Render and submit the non-dues income UI."""

    LIST_TEMPLATE = "income_batches_list.html"
    FORM_TEMPLATE = "income_batch_form.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.factory = ServiceFactory(conn)

    # ── List page ───────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        created_entry_number: str | None = None,
    ) -> IncomePageResponse:
        rows = IncomeBatchesRepository(self.conn).list_batches()
        batches = [
            {
                "id": r["id"],
                "posting_date": r["posting_date"],
                "description": r["income_description"],
                "total_amount": format_money(r['total_amount']),
                "bank_account": r["bank_account_name"],
                "income_account": (
                    r["category_name"]
                    or (
                        f"{r['income_account_number']} · {r['income_account_name']}"
                        if r["income_account_number"]
                        else ""
                    )
                ),
                "entry_number": r["entry_number"] or "",
                "notes": r["notes"] or "",
            }
            for r in rows
        ]
        ctx = {
            "heading": "Non-Dues Income",
            "description": (
                "Batched postings for income that doesn't come through "
                "owner dues — bank interest, one-off fees, gate-remote "
                "sales. Each batch credits one income category."
            ),
            "batches": batches,
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "income",
            "breadcrumb": "Transactions",
            "created_entry_number": created_entry_number,
        }
        return IncomePageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Form page ───────────────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        form_values: dict[str, str] | None = None,
        submitted_owner_rows: list[dict[str, str]] | None = None,
        error_message: str = "",
    ) -> IncomePageResponse:
        values = form_values or {}

        banks = [
            {
                "id": r["id"],
                "label": f"{r['account_name']} · {r['institution_name']}"
                         + (f" (…{r['account_last4']})" if r["account_last4"] else ""),
                "fund_code": r["fund_code"],
            }
            for r in BankAccountsRepository(self.conn).list_bank_accounts()
        ]
        income_categories = [
            {
                "id": r["id"],
                "label": r["name"],
                "fund_code": r["fund_code"],
            }
            for r in CategoriesRepository(self.conn).list_categories(
                category_type="INCOME"
            )
        ]
        lots = [
            {"id": r["id"], "label": _lot_label(r)}
            for r in LotsRepository(self.conn).list_lots()
        ]

        owner_rows = submitted_owner_rows or [
            {"lot_id": "", "amount": "", "memo": ""} for _ in range(4)
        ]

        ctx = {
            "heading": "Post Non-Dues Income",
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "income",
            "breadcrumb": "Transactions · Non-Dues Income",
            "banks": banks,
            "income_categories": income_categories,
            "lots": lots,
            "owner_rows": owner_rows,
            "values": {
                "posting_date": values.get("posting_date", _today()),
                "bank_account_id": values.get("bank_account_id", ""),
                "category_id": values.get("category_id", ""),
                "income_description": values.get("income_description", ""),
                "notes": values.get("notes", ""),
                "other_source": values.get("other_source", ""),
                "other_amount": values.get("other_amount", ""),
                "other_memo": values.get("other_memo", ""),
            },
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return IncomePageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Form POST ───────────────────────────────────────────────

    def handle_post(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
    ) -> tuple[str | None, IncomePageResponse | None]:
        by_index: dict[int, dict[str, str]] = {}
        for key, value in form_data.items():
            m = _ROW_KEY_RE.match(key)
            if not m:
                continue
            idx = int(m.group(1))
            by_index.setdefault(idx, {})[m.group(2)] = value
        submitted_owner_rows = [by_index[i] for i in sorted(by_index)]
        active_owner = [
            r for r in submitted_owner_rows
            if (r.get("amount") or "").strip() or (r.get("lot_id") or "").strip()
        ]

        other_source = (form_data.get("other_source") or "").strip()
        other_amount = (form_data.get("other_amount") or "").strip()
        other_memo = (form_data.get("other_memo") or "").strip() or None
        has_other = bool(other_source or other_amount)

        try:
            posting_date = _require(
                form_data.get("posting_date", ""), "Posting date"
            )
            bank_account_id = _parse_int(
                form_data.get("bank_account_id", ""), "Bank account"
            )
            category_id = _parse_int(
                form_data.get("category_id", ""), "Income category"
            )
            income_description = _require(
                form_data.get("income_description", ""), "Income description"
            )
            notes = (form_data.get("notes", "") or "").strip() or None

            rows: list[IncomeRow] = []
            for i, r in enumerate(active_owner, start=1):
                lot_id = _parse_int(r.get("lot_id", ""), f"Row {i}: lot")
                amount = _parse_positive_decimal(
                    r.get("amount", ""), f"Row {i}: amount"
                )
                rows.append(
                    IncomeRow(
                        amount=amount,
                        lot_id=lot_id,
                        memo=(r.get("memo") or "").strip() or None,
                    )
                )

            if has_other:
                if not other_source:
                    raise ValidationError(
                        "OTHER row: source description is required when "
                        "an OTHER amount is entered."
                    )
                if not other_amount:
                    raise ValidationError(
                        "OTHER row: amount is required when an OTHER "
                        "source is entered."
                    )
                amount_dec = _parse_positive_decimal(
                    other_amount, "OTHER: amount"
                )
                rows.append(
                    IncomeRow(
                        amount=amount_dec,
                        other_source=other_source,
                        memo=other_memo,
                    )
                )

            if not rows:
                raise ValidationError(
                    "Enter at least one row — either a lot row or the OTHER row."
                )

            result = self.factory.non_dues_income_service().post_batch(
                posting_date=posting_date,
                bank_account_id=bank_account_id,
                income_description=income_description,
                rows=rows,
                notes=notes,
                category_id=category_id,
            )
        except (ValidationError, NotFoundError, AccountingError) as exc:
            resp = self.render_form(
                org=org,
                theme=theme,
                form_values=form_data,
                submitted_owner_rows=submitted_owner_rows or None,
                error_message=str(exc),
            )
            return (None, resp)

        return (f"/income?created={result.income_batch_id}", None)


# ── Helpers ────────────────────────────────────────────────────────


def _lot_label(row: sqlite3.Row) -> str:
    street = row["street_address_1"] or ""
    owner = row["owner_names"] or "(no current owner)"
    bits = [str(row["lot_number"])]
    if street:
        bits.append(street)
    bits.append(owner)
    return " · ".join(bits)



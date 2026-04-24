"""Record Deposit — unified money-in entry point.

Replaces the separate *Record Payments*, *Resale Fee Payments*, and
*Other Income* screens with one grid that mirrors how a treasurer
actually works: one trip to the bank with a stack of checks (plus the
occasional one-off non-owner line). Each row picks a lot (owner
payment — drains matching-type open charges) or an "other source"
(rare, one-off income tagged to a category).

Every row on a saved deposit belongs to the same ``deposit_batches``
row, so the bank-import rule engine later matches one statement line
to the full slip total — the linkage the treasurer cares about.

Owner-payment rows have two drain modes:

- *regular* (default) — apply oldest-first against open DUES + LATE_FEE
  only. Prevents the classic bug where a dues check silently consumes
  an open resale fee and leaves the owner with a spurious credit balance.
- *specific* — the treasurer ticks exactly which charges this check
  covers (used for resale fees, special assessments, targeted cleanups).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.services.deposit_batch_service import DepositRow
from hoa_accounting.services.non_dues_income_service import IncomeRow
from hoa_accounting.web.template_engine import render_template


# Charge types drained by a *regular* owner payment. Anything else
# (RESALE_FEE, LEGAL_FEE, ad-hoc special assessments) requires the
# treasurer to explicitly target it via *specific charges* mode.
REGULAR_DRAIN_TYPES: tuple[str, ...] = ("DUES", "LATE_FEE")


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


class RecordDepositPages:
    """Render the deposit grid and handle submits."""

    TEMPLATE = "record_deposit.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Rendering ────────────────────────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict,
        theme: str,
        error_message: str = "",
        flash_message: str = "",
    ) -> PageResponse:
        accounts = self._conn.execute(
            """
            SELECT id, account_name, account_last4
            FROM bank_accounts
            WHERE active_flag = 1 OR active_flag IS NULL
            ORDER BY account_name
            """
        ).fetchall()
        lots = self._conn.execute(
            """
            SELECT l.id, l.lot_number,
                   COALESCE(o.display_name, '') AS owner_name
            FROM lots l
            LEFT JOIN (
                SELECT lot_id, owner_id FROM lot_ownership
                WHERE end_date IS NULL
                GROUP BY lot_id
            ) lo ON lo.lot_id = l.id
            LEFT JOIN owners o ON o.id = lo.owner_id
            ORDER BY l.lot_number
            """
        ).fetchall()
        categories = self._conn.execute(
            """
            SELECT id, name, group_name
            FROM categories
            WHERE active_flag = 1 AND category_type = 'INCOME'
            ORDER BY sort_order, name
            """
        ).fetchall()

        ctx = {
            "heading": "Record Deposit",
            "org": org,
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "record-deposit",
            "breadcrumb": "Money In",
            "parent_url": "/",
            "accounts": [dict(a) for a in accounts],
            "lots": [dict(l) for l in lots],
            "categories": [dict(c) for c in categories],
            "today": date.today().isoformat(),
            "error_message": error_message,
            "flash_message": flash_message,
        }
        status = 400 if error_message else 200
        return PageResponse(
            status_code=status,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    # ── Submit ───────────────────────────────────────────────────────────

    def handle_submit(
        self,
        *,
        deposit_date: str,
        bank_account_id: int,
        memo: str,
        rows: list[dict],
    ) -> tuple[str, str]:
        """Validate grid rows and post them as a single deposit batch.

        All owner-payment rows in the grid land on the same
        ``deposit_batches`` row; any *other source* rows land as
        ``income_batches`` tagged with the same ``deposit_batch_id`` so
        the bank-import matcher sees the full slip total.
        """
        if not deposit_date:
            return "/deposit", "Deposit date is required."
        try:
            date.fromisoformat(deposit_date)
        except ValueError:
            return "/deposit", "Invalid deposit date."
        if not bank_account_id:
            return "/deposit", "Bank account is required."

        owner_rows: list[DepositRow] = []
        other_rows: list[dict] = []
        errors: list[str] = []

        for idx, r in enumerate(rows, start=1):
            mode = (r.get("mode") or "").strip()
            # Empty rows are skipped silently so the grid can have spares.
            if not mode or mode == "blank":
                continue

            amount_raw = (r.get("amount") or "").strip().replace(",", "").replace("$", "")
            if not amount_raw:
                errors.append(f"Row {idx}: amount is required.")
                continue
            try:
                amount = Decimal(amount_raw)
            except InvalidOperation:
                errors.append(f"Row {idx}: invalid amount '{amount_raw}'.")
                continue
            if amount <= 0:
                errors.append(f"Row {idx}: amount must be positive.")
                continue

            memo_row = (r.get("memo") or "").strip()
            ref = (r.get("reference_number") or "").strip()

            if mode == "owner_regular":
                lot_raw = (r.get("lot_id") or "").strip()
                if not lot_raw.isdigit():
                    errors.append(f"Row {idx}: pick a lot.")
                    continue
                owner_rows.append(DepositRow(
                    lot_id=int(lot_raw),
                    amount=amount,
                    reference_number=ref or None,
                    memo=memo_row or None,
                    charge_type_filter=REGULAR_DRAIN_TYPES,
                ))
            elif mode == "owner_specific":
                lot_raw = (r.get("lot_id") or "").strip()
                if not lot_raw.isdigit():
                    errors.append(f"Row {idx}: pick a lot.")
                    continue
                # Expected CSV of assessment IDs, e.g. "42,45".
                ids_raw = (r.get("assessment_ids") or "").strip()
                ids: list[int] = []
                if ids_raw:
                    for piece in ids_raw.split(","):
                        piece = piece.strip()
                        if piece.isdigit():
                            ids.append(int(piece))
                if not ids:
                    errors.append(f"Row {idx}: tick at least one charge for specific-charges mode.")
                    continue
                owner_rows.append(DepositRow(
                    lot_id=int(lot_raw),
                    amount=amount,
                    reference_number=ref or None,
                    memo=memo_row or None,
                    apply_to_assessment_ids=tuple(ids),
                ))
            elif mode == "other":
                cat_raw = (r.get("category_id") or "").strip()
                if not cat_raw.isdigit():
                    errors.append(f"Row {idx}: pick a category for the other-source row.")
                    continue
                other_rows.append({
                    "amount": amount,
                    "category_id": int(cat_raw),
                    "description": memo_row or "Non-owner income",
                })
            else:
                errors.append(f"Row {idx}: unknown row mode '{mode}'.")

        if errors:
            return "/deposit", " ".join(errors)
        if not owner_rows and not other_rows:
            return "/deposit", "Add at least one row before saving."

        factory = ServiceFactory(self._conn)

        # Post the owner-payment batch first (if any) so we have a
        # deposit_batch_id to attach any other-source income rows to.
        # If the deposit is pure other-source (no owner payments) we
        # still create a deposit_batches row with one synthetic income
        # line — treasurer can post one if they actually deposited e.g.
        # a vendor refund alone. For now, require at least one owner
        # row when there are no other rows, and vice versa.
        deposit_batch_id: int | None = None
        if owner_rows:
            result = factory.deposit_batch_service().post_batch(
                deposit_date=deposit_date,
                bank_account_id=int(bank_account_id),
                rows=owner_rows,
                notes=memo or None,
            )
            deposit_batch_id = result.deposit_batch_id

        for line in other_rows:
            # Each other-source line is its own small income batch — the
            # service is happy to take a single-row batch and gives us a
            # tidy audit trail per category.
            factory.non_dues_income_service().post_batch(
                posting_date=deposit_date,
                bank_account_id=int(bank_account_id),
                income_description=line["description"],
                rows=[IncomeRow(amount=str(line["amount"]), other_source="OTHER")],
                category_id=line["category_id"],
                deposit_batch_id=deposit_batch_id,
                notes=memo or None,
            )

        count = len(owner_rows) + len(other_rows)
        return (
            f"/deposit?msg=Saved+{count}+line(s)+on+deposit+batch"
            f"{'+%d' % deposit_batch_id if deposit_batch_id else ''}.",
            "",
        )

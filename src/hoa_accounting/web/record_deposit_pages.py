"""Record Deposit — unified money-in entry point.

Each grid row is a single income Category. The category drives behavior:

- *regular owner payment* (DUES, LATE_FEE) — pick a lot; check drains
  open DUES + LATE_FEE oldest-first.
- *specific owner payment* (RESALE_FEE) — pick a lot; check drains open
  charges of that category only (oldest-first if nothing ticked, or
  exactly the ticked ones).
- *other income* (BANK_INTEREST, RESERVE_INTEREST, OTHER_INCOME, anything
  unmapped) — non-owner deposit; just an amount + memo, no lot.

Every row on a saved deposit lands on the same ``deposit_batches`` row,
so the bank-import rule engine later matches one statement line to the
full slip total.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from hoa_accounting.db.transaction import transaction
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.services.deposit_batch_service import DepositRow
from hoa_accounting.services.non_dues_income_service import IncomeRow
from hoa_accounting.web.template_engine import render_template


# Map category code → row behavior + which open charges this category
# drains when the row is an owner payment.
#
# Categories not listed here default to behavior="other" (non-owner
# income — no lot picker, no charge drain).
CATEGORY_BEHAVIOR: dict[str, dict] = {
    "DUES":             {"behavior": "regular",  "charge_types": ("DUES", "LATE_FEE")},
    "LATE_FEE":         {"behavior": "regular",  "charge_types": ("DUES", "LATE_FEE")},
    "RESALE_FEE":       {"behavior": "specific", "charge_types": ("RESALE_FEE",)},
    "BANK_INTEREST":    {"behavior": "other",    "charge_types": ()},
    "RESERVE_INTEREST": {"behavior": "other",    "charge_types": ()},
    "OTHER_INCOME":     {"behavior": "other",    "charge_types": ()},
}


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
        prior_deposit_date: str = "",
        prior_bank_account_id: str = "",
        prior_memo: str = "",
        prior_rows: list[dict] | None = None,
    ) -> PageResponse:
        accounts = self._conn.execute(
            """
            SELECT id, account_name, account_last4, account_type
            FROM bank_accounts
            WHERE active_flag = 1 OR active_flag IS NULL
            ORDER BY account_name
            """
        ).fetchall()
        # Default the bank dropdown to the operating account so the
        # treasurer doesn't have to pick it on every deposit.
        default_bank_id: int | None = None
        for a in accounts:
            if "operating" in (a["account_name"] or "").lower():
                default_bank_id = int(a["id"])
                break
        if default_bank_id is None:
            for a in accounts:
                if (a["account_type"] or "").upper() == "CHECKING":
                    default_bank_id = int(a["id"])
                    break
        # For each lot, pick the first owner alphabetically (by display_name)
        # among current (end_date IS NULL) ownerships. Show first + last name
        # in the dropdown; fall back to display_name for entity-style owners
        # that have no first/last set.
        lots = self._conn.execute(
            """
            SELECT
                l.id,
                l.lot_number,
                COALESCE(
                    NULLIF(TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,'')), ''),
                    o.display_name,
                    ''
                ) AS owner_name
            FROM lots l
            LEFT JOIN lot_ownership lo
                   ON lo.id = (
                        SELECT lo2.id
                        FROM lot_ownership lo2
                        JOIN owners o2 ON o2.id = lo2.owner_id
                        WHERE lo2.lot_id = l.id AND lo2.end_date IS NULL
                        ORDER BY o2.display_name COLLATE NOCASE
                        LIMIT 1
                   )
            LEFT JOIN owners o ON o.id = lo.owner_id
            ORDER BY l.lot_number
            """
        ).fetchall()
        cat_rows = self._conn.execute(
            """
            SELECT id, code, name, group_name
            FROM categories
            WHERE active_flag = 1 AND category_type = 'INCOME'
            ORDER BY sort_order, name
            """
        ).fetchall()
        # Decorate each category with its behavior + charge_types so the
        # template's JS can swap row UI by reading data attributes.
        categories: list[dict] = []
        for c in cat_rows:
            spec = CATEGORY_BEHAVIOR.get(
                str(c["code"] or "").upper(),
                {"behavior": "other", "charge_types": ()},
            )
            categories.append({
                "id": c["id"],
                "code": c["code"] or "",
                "name": c["name"] or "",
                "group_name": c["group_name"] or "",
                "behavior": spec["behavior"],
                "charge_types": ",".join(spec["charge_types"]),
            })

        ctx = {
            "heading": "Record Deposit",
            "org": org,
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "record-deposit",
            "breadcrumb": "Money In",
            "parent_url": "/",
            "accounts": [dict(a) for a in accounts],
            "default_bank_id": default_bank_id,
            "lots": [dict(l) for l in lots],
            "categories": categories,
            "today": date.today().isoformat(),
            "error_message": error_message,
            "flash_message": flash_message,
            "prior_deposit_date": prior_deposit_date,
            "prior_bank_account_id": prior_bank_account_id,
            "prior_memo": prior_memo,
            "prior_rows": prior_rows or [],
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
        """Validate grid rows and post them as a single deposit batch."""
        if not deposit_date:
            return "/deposit", "Deposit date is required."
        try:
            date.fromisoformat(deposit_date)
        except ValueError:
            return "/deposit", "Invalid deposit date."
        if not bank_account_id:
            return "/deposit", "Bank account is required."

        # Build a quick lookup from category id → (code, behavior, charge_types).
        cat_lookup: dict[int, dict] = {}
        for c in self._conn.execute(
            """
            SELECT id, code FROM categories
            WHERE active_flag = 1 AND category_type = 'INCOME'
            """
        ).fetchall():
            cat_spec = CATEGORY_BEHAVIOR.get(
                str(c["code"] or "").upper(),
                {"behavior": "other", "charge_types": ()},
            )
            cat_lookup[int(c["id"])] = {
                "code": c["code"] or "",
                "behavior": cat_spec["behavior"],
                "charge_types": cat_spec["charge_types"],
            }

        owner_rows: list[DepositRow] = []
        other_rows: list[dict] = []
        errors: list[str] = []

        for idx, r in enumerate(rows, start=1):
            cat_raw = (r.get("category_id") or "").strip()
            amount_raw = (r.get("amount") or "").strip().replace(",", "").replace("$", "")
            lot_raw = (r.get("lot_id") or "").strip()
            ids_raw = (r.get("assessment_ids") or "").strip()

            # A row with no amount AND no lot AND no description is a
            # blank spare — skip it silently. The category default is
            # pre-selected (DUES), so cat_raw alone doesn't indicate intent.
            other_memo_raw = (r.get("memo") or "").strip()
            if not amount_raw and not lot_raw and not other_memo_raw:
                continue

            if not cat_raw.isdigit():
                errors.append(f"Row {idx}: pick a category.")
                continue
            cat_id = int(cat_raw)
            spec = cat_lookup.get(cat_id)
            if spec is None:
                errors.append(f"Row {idx}: unknown category.")
                continue

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

            behavior = spec["behavior"]

            if behavior == "regular":
                if not lot_raw.isdigit():
                    errors.append(f"Row {idx}: pick a lot.")
                    continue
                owner_rows.append(DepositRow(
                    lot_id=int(lot_raw),
                    amount=amount,
                    reference_number=ref or None,
                    memo=memo_row or None,
                    charge_type_filter=spec["charge_types"],
                ))
            elif behavior == "specific":
                if not lot_raw.isdigit():
                    errors.append(f"Row {idx}: pick a lot.")
                    continue
                ids: list[int] = []
                if ids_raw:
                    for piece in ids_raw.split(","):
                        piece = piece.strip()
                        if piece.isdigit():
                            ids.append(int(piece))
                if ids:
                    owner_rows.append(DepositRow(
                        lot_id=int(lot_raw),
                        amount=amount,
                        reference_number=ref or None,
                        memo=memo_row or None,
                        apply_to_assessment_ids=tuple(ids),
                    ))
                else:
                    # No specific charges ticked — drain matching-type
                    # open charges oldest-first (e.g. resale fees only).
                    owner_rows.append(DepositRow(
                        lot_id=int(lot_raw),
                        amount=amount,
                        reference_number=ref or None,
                        memo=memo_row or None,
                        charge_type_filter=spec["charge_types"],
                    ))
            else:  # "other"
                other_rows.append({
                    "amount": amount,
                    "category_id": cat_id,
                    "description": memo_row or "Non-owner income",
                })

        if errors:
            return "/deposit", " ".join(errors)
        if not owner_rows and not other_rows:
            return "/deposit", "Add at least one row before saving."

        factory = ServiceFactory(self._conn)

        # The deposit slip is one logical operation: owner-payment batch,
        # any non-owner income lines, and the synthetic batch shim if
        # no owner_rows existed all need to land or none of them do.
        # The two services use ``with transaction(...)`` internally,
        # which becomes a savepoint when nested inside this outer block.
        with transaction(self._conn):
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
                factory.non_dues_income_service().post_batch(
                    posting_date=deposit_date,
                    bank_account_id=int(bank_account_id),
                    income_description=line["description"],
                    rows=[IncomeRow(amount=str(line["amount"]), other_source="OTHER")],
                    category_id=line["category_id"],
                    deposit_batch_id=deposit_batch_id,
                    notes=memo or None,
                )

            # If there were no owner_rows the deposit_batch wasn't created
            # above; create a synthetic single-row batch so the Deposits
            # report and the OFX matcher see the full slip total.
            if deposit_batch_id is None and other_rows:
                other_total = sum(line["amount"] for line in other_rows)
                cur = self._conn.execute(
                    """INSERT INTO deposit_batches
                       (deposit_date, bank_account_id, total_amount, notes)
                       VALUES (?, ?, ?, ?)""",
                    (deposit_date, int(bank_account_id), str(other_total), memo or None),
                )
                deposit_batch_id = int(cur.lastrowid or 0)
                # Attach the income_batches we just created to this new batch.
                self._conn.execute(
                    "UPDATE income_batches SET deposit_batch_id = ? "
                    "WHERE deposit_batch_id IS NULL "
                    "  AND posting_date = ? AND bank_account_id = ?",
                    (deposit_batch_id, deposit_date, int(bank_account_id)),
                )

            # Update deposit_batches.total_amount to reflect the FULL slip —
            # owner payments + other-source income — so the OFX matcher and
            # Deposits report see what actually hit the bank.
            if deposit_batch_id is not None:
                self._conn.execute(
                    """
                    UPDATE deposit_batches
                       SET total_amount = (
                            COALESCE((SELECT SUM(p.amount) FROM payments p
                                      WHERE p.deposit_batch_id = ?), 0)
                          + COALESCE((SELECT SUM(ib.total_amount) FROM income_batches ib
                                      WHERE ib.deposit_batch_id = ?), 0)
                       )
                     WHERE id = ?
                    """,
                    (deposit_batch_id, deposit_batch_id, deposit_batch_id),
                )

        count = len(owner_rows) + len(other_rows)
        return (
            f"/deposit?msg=Saved+{count}+line(s)+on+deposit+batch"
            f"{'+%d' % deposit_batch_id if deposit_batch_id else ''}.",
            "",
        )

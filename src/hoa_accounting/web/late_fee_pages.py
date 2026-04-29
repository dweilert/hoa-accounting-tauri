"""Late Fee page — post interest charges on delinquent dues and assessments.

Flow
----
1. GET /late-fees
   Lot selector only.  No charges shown until a lot is chosen.

2. GET /late-fees?lot_id=<n>
   Loads the lot's open DUES/SPECIAL charges plus any previously posted
   LATE_FEE charges so the treasurer can see the full picture.
   The rate and through-date default at the top; per-row delinquent dates
   default to each charge's due_date.  JS calculates interest live.

3. POST /late-fees/post
   Validates, posts one LATE_FEE assessment per selected row, all
   crediting account 4050 (Late Fee Income).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date as _date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError
from hoa_accounting.validators.format import format_currency
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.web.template_engine import render_template

_DEFAULT_RATE = Decimal("10.00")   # 10 % per annum per bylaws
_LATE_FEE_ACCOUNT = "4050"         # Late Fee Income (seeded in migration 0013)
_AR_DEFAULT = "1100"


def _today() -> str:
    return _date.today().isoformat()


def _days_between(from_iso: str, to_iso: str) -> int:
    """Return calendar days from_iso → to_iso; 0 if negative."""
    try:
        d1 = _date.fromisoformat(from_iso)
        d2 = _date.fromisoformat(to_iso)
        return max(0, (d2 - d1).days)
    except (ValueError, TypeError):
        return 0


def _calc_interest(principal: Decimal, rate_pct: Decimal, days: int) -> Decimal:
    """principal × rate% × days/365, rounded to 2 dp."""
    if days <= 0 or rate_pct <= 0 or principal <= 0:
        return Decimal("0.00")
    result = principal * (rate_pct / 100) * Decimal(days) / Decimal("365")
    return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class LateFeePageResponse:
    status_code: int
    body_html: str


class LateFeePages:
    """Render + handle POST for the Late Fee screen."""

    TEMPLATE = "late_fee.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.factory = ServiceFactory(conn)

    # ── helpers ─────────────────────────────────────────────────────────

    def _resolve_late_fee_account(self) -> tuple[int | None, str]:
        """Return (category_id, label) for the LATE_FEE category, or (None, error)."""
        row = self.conn.execute(
            "SELECT id, code, name, active_flag FROM categories WHERE code = 'LATE_FEE'"
        ).fetchone()
        if row is None:
            return None, "LATE_FEE category not found. Add it on the Categories page."
        if not int(row["active_flag"]):
            return None, "LATE_FEE category is inactive."
        return int(row["id"]), f"{row['code']} · {row['name']}"

    def _lot_options(self) -> list[dict]:
        # One row per lot. When a lot has multiple current owners we show
        # the one that sorts first by (last_name, first_name) — keeps the
        # dropdown compact and lets the user scan it alphabetically.
        rows = self.conn.execute(
            """
            WITH first_owner AS (
                SELECT
                    lo.lot_id,
                    o.id                              AS owner_id,
                    COALESCE(o.first_name, '')        AS first_name,
                    COALESCE(o.last_name, '')         AS last_name,
                    ROW_NUMBER() OVER (
                        PARTITION BY lo.lot_id
                        ORDER BY COALESCE(o.last_name, ''),
                                 COALESCE(o.first_name, ''),
                                 o.id
                    ) AS rn
                FROM lot_ownership lo
                JOIN owners o ON o.id = lo.owner_id
                WHERE lo.end_date IS NULL
            )
            SELECT
                l.id,
                l.lot_number,
                fo.owner_id,
                TRIM(fo.first_name || ' ' || fo.last_name) AS owner_name
            FROM lots l
            LEFT JOIN first_owner fo
                   ON fo.lot_id = l.id AND fo.rn = 1
            WHERE l.active_flag = 1
            ORDER BY l.lot_number COLLATE NOCASE
            """
        ).fetchall()
        options = []
        for r in rows:
            owner = r["owner_name"] or "(no owner)"
            label = f"Lot {r['lot_number']} · {owner}"
            options.append({"id": r["id"], "label": label, "owner_id": r["owner_id"]})
        return options

    def _load_lot_charges(self, lot_id: int, through_date: str) -> dict:
        """Return open chargeable rows + late fee history for a lot."""
        lot = LotsRepository(self.conn).get_lot_with_owner(lot_id)
        if lot is None:
            return {}

        owner_id = lot["owner_id"]
        if owner_id is None:
            return {"lot": lot, "chargeable": [], "history": []}

        all_open = AssessmentsRepository(self.conn).list_open_for_owner(owner_id)

        chargeable = []
        history = []
        for row in all_open:
            ct = (row["charge_type"] or "DUES").upper()
            if ct == "LATE_FEE":
                history.append(dict(row))
            elif ct in ("DUES", "SPECIAL"):
                delinquent_date = row["due_date"] or row["assessment_date"]
                principal = Decimal(str(row["amount"]))
                remaining = principal - Decimal(str(row["already_applied"]))
                days = _days_between(delinquent_date, through_date)
                chargeable.append({
                    "id": row["id"],
                    "description": row["description"],
                    "amount": principal,
                    "remaining": remaining,
                    "due_date": row["due_date"],
                    "assessment_date": row["assessment_date"],
                    "charge_type": ct,
                    "delinquent_date": delinquent_date,
                    "days": days,
                    # interest calculated with default rate; JS recalculates live
                    "interest": _calc_interest(remaining, _DEFAULT_RATE, days),
                })

        return {"lot": lot, "chargeable": chargeable, "history": history}

    # ── Render ──────────────────────────────────────────────────────────

    def render_page(
        self,
        *,
        org: dict | None,
        theme: str,
        lot_id: int | None = None,
        rate_pct: str = "",
        through_date: str = "",
        form_values: dict[str, str] | None = None,
        error_message: str = "",
        flash_message: str = "",
    ) -> LateFeePageResponse:
        org = org or {}
        fv = form_values or {}

        lf_account_id, lf_account_label = self._resolve_late_fee_account()
        if lf_account_id is None:
            error_message = error_message or lf_account_label

        eff_rate = (fv.get("rate_pct") or rate_pct or "").strip() or str(_DEFAULT_RATE)
        eff_through = (fv.get("through_date") or through_date or "").strip() or _today()

        lot_options = self._lot_options()

        # Restore lot_id from form repost if available.
        if fv.get("lot_id"):
            try:
                lot_id = int(fv["lot_id"])
            except (TypeError, ValueError):
                pass

        lot_data: dict = {}
        if lot_id:
            try:
                rate_dec = Decimal(eff_rate)
            except InvalidOperation:
                rate_dec = _DEFAULT_RATE
            lot_data = self._load_lot_charges(lot_id, eff_through)
            # Re-calculate with the actual rate (form values may differ from default).
            for row in lot_data.get("chargeable", []):
                row["interest"] = _calc_interest(row["remaining"], rate_dec, row["days"])
                # Restore any user-overridden values from a validation-error repost.
                row_key = str(row["id"])
                if fv.get(f"row_{row_key}_delinquent_date"):
                    row["delinquent_date"] = fv[f"row_{row_key}_delinquent_date"]
                    row["days"] = _days_between(row["delinquent_date"], eff_through)
                    row["interest"] = _calc_interest(row["remaining"], rate_dec, row["days"])
                if fv.get(f"row_{row_key}_interest"):
                    try:
                        row["interest"] = Decimal(fv[f"row_{row_key}_interest"]).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                    except InvalidOperation:
                        pass

        ctx = {
            "heading": "Post Late Fee",
            "org": org,
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "late-fees",
            "breadcrumb": "Transactions",
            "lot_options": lot_options,
            "selected_lot_id": lot_id,
            "rate_pct": eff_rate,
            "through_date": eff_through,
            "lot_data": lot_data,
            "lf_account_label": lf_account_label if lf_account_id else "",
            "error_message": error_message,
            "flash_message": flash_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return LateFeePageResponse(
            status_code=status,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    # ── POST ────────────────────────────────────────────────────────────

    def handle_post(
        self,
        *,
        form_data: dict[str, str],
        org: dict | None,
        theme: str,
    ) -> tuple[str | None, LateFeePageResponse | None]:
        org = org or {}

        def _err(msg: str) -> tuple[None, LateFeePageResponse]:
            return None, self.render_page(
                org=org, theme=theme,
                form_values=form_data,
                error_message=msg,
            )

        # ── Validate header fields ──
        try:
            lot_id = int((form_data.get("lot_id") or "").strip())
        except (TypeError, ValueError):
            return _err("Lot is required.")

        try:
            rate_pct = Decimal((form_data.get("rate_pct") or "").strip())
            if rate_pct <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            return _err("Rate must be a positive number.")

        through_date = (form_data.get("through_date") or "").strip()
        if not through_date:
            return _err("Through date is required.")

        entry_date = (form_data.get("entry_date") or "").strip() or _today()

        # ── Resolve LATE_FEE category ──
        lf_category_id, lf_err = self._resolve_late_fee_account()
        if lf_category_id is None:
            return _err(lf_err)

        # ── Collect selected rows ──
        lot = LotsRepository(self.conn).get_lot_with_owner(lot_id)
        if lot is None:
            return _err("Lot not found.")
        owner_id = lot["owner_id"]
        if owner_id is None:
            return _err("This lot has no current owner.")

        rows_to_post: list[dict] = []
        for key, value in form_data.items():
            if not key.startswith("row_") or not key.endswith("_selected"):
                continue
            try:
                assessment_id = int(key[4:-9])  # strip "row_" and "_selected"
            except ValueError:
                continue

            interest_raw = (form_data.get(f"row_{assessment_id}_interest") or "").strip()
            delinquent_date = (
                form_data.get(f"row_{assessment_id}_delinquent_date") or ""
            ).strip()

            try:
                interest = Decimal(interest_raw).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            except (InvalidOperation, ValueError):
                return _err(f"Invalid interest amount for row {assessment_id}.")

            if interest <= 0:
                continue  # silently skip zero rows

            if not delinquent_date:
                return _err(f"Delinquent date is required for each selected charge.")

            rows_to_post.append({
                "assessment_id": assessment_id,
                "delinquent_date": delinquent_date,
                "interest": interest,
            })

        if not rows_to_post:
            return _err("Select at least one charge and ensure the interest amount is greater than zero.")

        # ── Post one LATE_FEE assessment per selected row ──
        try:
            svc = self.factory.assessment_service()
            posted = 0
            for row in rows_to_post:
                # Fetch the original charge description for context.
                orig = self.conn.execute(
                    "SELECT description, due_date FROM assessments WHERE id = ?",
                    (row["assessment_id"],),
                ).fetchone()
                orig_desc = orig["description"] if orig else f"charge #{row['assessment_id']}"
                desc = (
                    f"Late fee on: {orig_desc} "
                    f"(delinquent {row['delinquent_date']} through {through_date}, "
                    f"{rate_pct}% p.a.)"
                )
                svc.post_assessment(
                    entry_date=entry_date,
                    lot_id=lot_id,
                    owner_id=owner_id,
                    amount=row["interest"],
                    description=desc,
                    category_id=lf_category_id,
                    charge_type="LATE_FEE",
                    due_date=entry_date,
                )
                posted += 1
        except (ValidationError, NotFoundError, AccountingError) as exc:
            return _err(str(exc))

        from urllib.parse import quote
        total = sum(r["interest"] for r in rows_to_post)
        msg = (
            f"Posted {posted} late fee charge(s) totalling "
            f"{format_currency(total)} for Lot {lot['lot_number']}."
        )
        return f"/late-fees?lot_id={lot_id}&msg={quote(msg)}", None

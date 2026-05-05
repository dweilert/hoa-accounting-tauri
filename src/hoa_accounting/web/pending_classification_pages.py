"""Pending Classifications — pre-bank entry of incoming payments.

A pending classification captures the treasurer's knowledge of an
incoming payment (who, which lot, what category, how much) without
posting anything to the ledger. Posting happens later, when the OFX
import confirms the bank received the deposit.

Routes handled (wired up in routes/bank.py):
  GET  /pending-classifications              — list page
  GET  /pending-classifications/new          — entry form
  POST /pending-classifications/new          — save new
  GET  /pending-classifications/<id>/edit    — edit form
  POST /pending-classifications/<id>/edit    — save edits
  POST /pending-classifications/<id>/cancel  — mark CANCELLED
  POST /pending-classifications/<id>/delete  — hard-delete (PENDING only)
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from typing import Any

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.pending_classifications_repo import (
    PendingClassificationsRepository,
)
from hoa_accounting.services.pending_classification_matcher import (
    PendingClassificationMatcher,
)
from hoa_accounting.services.pending_classification_poster import (
    PendingClassificationPoster,
)
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


_BASE_CTX = {
    "active_nav": "homeowners",
    "page_key": "pending-classifications",
    "breadcrumb": "Homeowners",
}


class PendingClassificationPages:
    """Render and handle the pending-classification pages."""

    LIST_TEMPLATE = "pending_classifications_list.html"
    FORM_TEMPLATE = "pending_classification_form.html"
    MATCH_TEMPLATE = "pending_classification_match.html"
    POST_TEMPLATE = "pending_classification_post.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.repo = PendingClassificationsRepository(conn)
        self.assessments_repo = AssessmentsRepository(conn)
        self.matcher = PendingClassificationMatcher(conn)
        self.poster = PendingClassificationPoster(conn)

    # ── List page ────────────────────────────────────────────────────

    def render_list(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        status_filter: str = "",
        flash_message: str = "",
        error_message: str = "",
    ) -> PageResponse:
        rows = self.repo.list_for_display(
            status=status_filter or None,
            limit=500,
        )
        items = [dict(r) for r in rows]
        ctx = {
            **_BASE_CTX,
            "heading": "Pending Classifications",
            "org": org or {},
            "theme": theme,
            "items": items,
            "status_filter": status_filter,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return PageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.LIST_TEMPLATE, ctx),
        )

    # ── Entry / Edit form ────────────────────────────────────────────

    def render_form(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        pc_id: int | None = None,
        form_values: dict[str, str] | None = None,
        flash_message: str = "",
        error_message: str = "",
    ) -> PageResponse:
        is_edit = pc_id is not None
        values: dict[str, str] = {}

        if pc_id is not None and form_values is None:
            row = self.repo.get(pc_id)
            if row is None:
                return PageResponse(
                    status_code=HTTPStatus.NOT_FOUND,
                    body_html="<h1>Pending classification not found</h1>",
                )
            values = {
                "classification_date": row["classification_date"] or "",
                "expected_deposit_date": row["expected_deposit_date"] or "",
                "bank_account_id": str(row["bank_account_id"] or ""),
                "lot_id": str(row["lot_id"] or ""),
                "owner_id": str(row["owner_id"] or ""),
                "amount": str(row["amount"] or ""),
                "payment_method": row["payment_method"] or "CHECK",
                "reference_number": row["reference_number"] or "",
                "category_id": str(row["category_id"] or ""),
                "charge_type": row["charge_type"] or "",
                "memo": row["memo"] or "",
                "status": row["status"] or "PENDING",
                "apply_to_assessment_ids": row["apply_to_assessment_ids"] or "",
            }
        else:
            values = form_values or {}

        # Reference data
        bank_accounts = self.conn.execute("""
            SELECT id, account_name, account_last4
            FROM bank_accounts
            WHERE active_flag = 1 OR active_flag IS NULL
            ORDER BY account_name COLLATE NOCASE
            """).fetchall()

        # Lots with current owner for the dropdown
        lots = self.conn.execute("""
            SELECT
                l.id,
                l.lot_number,
                COALESCE(
                    NULLIF(TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,'')), ''),
                    o.display_name,
                    ''
                ) AS owner_name,
                lo.owner_id AS current_owner_id
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
            WHERE l.active_flag = 1 OR l.active_flag IS NULL
            ORDER BY l.lot_number COLLATE NOCASE
            """).fetchall()

        categories = self.conn.execute("""
            SELECT id, code, name
            FROM categories
            WHERE category_type = 'INCOME' AND active_flag = 1
            ORDER BY name COLLATE NOCASE
            """).fetchall()

        # Default the bank dropdown to the operating account on a fresh form
        default_bank_id: int | None = None
        if not values.get("bank_account_id"):
            for a in bank_accounts:
                if "operating" in (a["account_name"] or "").lower():
                    default_bank_id = int(a["id"])
                    break
            if default_bank_id is None and bank_accounts:
                default_bank_id = int(bank_accounts[0]["id"])

        # Open assessments for the currently-selected lot (specific-charges mode)
        open_assessments: list[dict[str, Any]] = []
        selected_apply_ids: set[int] = set()
        lot_raw = values.get("lot_id", "")
        if lot_raw and lot_raw.isdigit():
            owner_id_for_lot = self._current_owner_for_lot(int(lot_raw))
            if owner_id_for_lot is not None:
                rows_oa = self.assessments_repo.list_open_for_owner(owner_id_for_lot)
                open_assessments = [
                    {
                        "id": int(r["id"]),
                        "description": (r["description"] or ""),
                        "charge_type": (r["charge_type"] or ""),
                        "amount": str(r["amount"]),
                        "already_applied": str(r["already_applied"] or 0),
                        "outstanding": str(
                            Decimal(str(r["amount"]))
                            - Decimal(str(r["already_applied"] or 0))
                        ),
                        "due_date": (r["due_date"] or ""),
                        "status": (r["status"] or ""),
                    }
                    for r in rows_oa
                ]
            ids_raw = values.get("apply_to_assessment_ids", "")
            if ids_raw:
                try:
                    selected_apply_ids = {int(x) for x in json.loads(ids_raw) if x}
                except (ValueError, TypeError, json.JSONDecodeError):
                    selected_apply_ids = set()

        ctx = {
            **_BASE_CTX,
            "heading": (
                "Edit Pending Classification"
                if is_edit
                else "New Pending Classification"
            ),
            "breadcrumb": "Homeowners · Pending Classifications",
            "parent_url": "/pending-classifications",
            "org": org or {},
            "theme": theme,
            "is_edit": is_edit,
            "pc_id": pc_id,
            "values": {
                "classification_date": values.get(
                    "classification_date", date.today().isoformat()
                ),
                "expected_deposit_date": values.get("expected_deposit_date", ""),
                "bank_account_id": values.get(
                    "bank_account_id",
                    str(default_bank_id) if default_bank_id else "",
                ),
                "lot_id": values.get("lot_id", ""),
                "owner_id": values.get("owner_id", ""),
                "amount": values.get("amount", ""),
                "payment_method": values.get("payment_method", "CHECK"),
                "reference_number": values.get("reference_number", ""),
                "category_id": values.get("category_id", ""),
                "charge_type": values.get("charge_type", ""),
                "memo": values.get("memo", ""),
                "status": values.get("status", "PENDING"),
                "apply_to_assessment_ids": values.get("apply_to_assessment_ids", ""),
            },
            "open_assessments": open_assessments,
            "selected_apply_ids": list(selected_apply_ids),
            "bank_accounts": [dict(r) for r in bank_accounts],
            "lots": [dict(r) for r in lots],
            "categories": [dict(r) for r in categories],
            "flash_message": flash_message,
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return PageResponse(
            status_code=status,
            body_html=render_template(self.FORM_TEMPLATE, ctx),
        )

    # ── Submit (new) ─────────────────────────────────────────────────

    def handle_add(
        self,
        *,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
        apply_to_assessment_ids: list[str] | None = None,
    ) -> tuple[str | None, PageResponse | None]:
        try:
            parsed = self._parse_form(
                form_data,
                apply_to_assessment_ids=apply_to_assessment_ids,
            )
            self.repo.insert(**parsed)
            self.conn.commit()
        except ValidationError as exc:
            # Echo the explicit-charges selection back into form_values
            # so the form re-render keeps the boxes checked.
            redisplay = dict(form_data)
            if apply_to_assessment_ids:
                ids_int = [int(x) for x in apply_to_assessment_ids if x.isdigit()]
                redisplay["apply_to_assessment_ids"] = json.dumps(ids_int)
            return None, self.render_form(
                org=org,
                theme=theme,
                form_values=redisplay,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return "/pending-classifications?msg=Classification+saved.", None

    # ── Submit (edit) ────────────────────────────────────────────────

    def handle_edit(
        self,
        *,
        pc_id: int,
        form_data: dict[str, str],
        org: dict[str, object] | None,
        theme: str,
        apply_to_assessment_ids: list[str] | None = None,
    ) -> tuple[str | None, PageResponse | None]:
        try:
            existing = self.repo.get(pc_id)
            if existing is None:
                raise ValidationError("Classification not found.")
            if existing["status"] not in ("PENDING", "MATCHED"):
                raise ValidationError(
                    f"Cannot edit a classification in status {existing['status']}."
                )
            parsed = self._parse_form(
                form_data,
                apply_to_assessment_ids=apply_to_assessment_ids,
            )
            # update() takes the same kwargs except created_by_user_id
            parsed.pop("created_by_user_id", None)
            self.repo.update(pc_id, **parsed)
            self.conn.commit()
        except ValidationError as exc:
            redisplay = dict(form_data)
            if apply_to_assessment_ids:
                ids_int = [int(x) for x in apply_to_assessment_ids if x.isdigit()]
                redisplay["apply_to_assessment_ids"] = json.dumps(ids_int)
            return None, self.render_form(
                org=org,
                theme=theme,
                pc_id=pc_id,
                form_values=redisplay,
                error_message=str(exc),
            )
        except Exception:
            self.conn.rollback()
            raise
        return (
            f"/pending-classifications/{pc_id}/edit?msg=Classification+updated.",
            None,
        )

    # ── Cancel / Delete ──────────────────────────────────────────────

    def handle_cancel(self, *, pc_id: int) -> tuple[str | None, PageResponse | None]:
        try:
            existing = self.repo.get(pc_id)
            if existing is None:
                raise ValidationError("Classification not found.")
            if existing["status"] == "POSTED":
                raise ValidationError(
                    "Cannot cancel a posted classification — void the payment instead."
                )
            self.repo.cancel(pc_id)
            self.conn.commit()
        except ValidationError as exc:
            return f"/pending-classifications?err={str(exc).replace(' ', '+')}", None
        except Exception:
            self.conn.rollback()
            raise
        return "/pending-classifications?msg=Classification+cancelled.", None

    def handle_delete(self, *, pc_id: int) -> tuple[str | None, PageResponse | None]:
        try:
            existing = self.repo.get(pc_id)
            if existing is None:
                raise ValidationError("Classification not found.")
            if existing["status"] != "PENDING":
                raise ValidationError(
                    f"Cannot delete a classification in status {existing['status']}. "
                    "Cancel it instead."
                )
            self.repo.delete(pc_id)
            self.conn.commit()
        except ValidationError as exc:
            return f"/pending-classifications?err={str(exc).replace(' ', '+')}", None
        except Exception:
            self.conn.rollback()
            raise
        return "/pending-classifications?msg=Classification+deleted.", None

    # ── Helpers ──────────────────────────────────────────────────────

    def _parse_form(
        self,
        form_data: dict[str, str],
        *,
        apply_to_assessment_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        classification_date = (form_data.get("classification_date") or "").strip()
        if not classification_date:
            raise ValidationError("Classification date is required.")

        bank_raw = (form_data.get("bank_account_id") or "").strip()
        if not bank_raw.isdigit():
            raise ValidationError("Pick a bank account.")

        amount_raw = (form_data.get("amount") or "").strip().replace(",", "")
        if not amount_raw:
            raise ValidationError("Amount is required.")
        try:
            amount = Decimal(amount_raw)
        except InvalidOperation as exc:
            raise ValidationError(f"Invalid amount: {amount_raw}") from exc
        if amount <= 0:
            raise ValidationError("Amount must be greater than zero.")

        payment_method = (form_data.get("payment_method") or "CHECK").strip().upper()
        if payment_method not in {"CHECK", "ACH", "CASH", "CARD", "OTHER"}:
            raise ValidationError(f"Invalid payment method: {payment_method}")

        # Optional fields
        expected = (form_data.get("expected_deposit_date") or "").strip() or None

        lot_raw = (form_data.get("lot_id") or "").strip()
        lot_id = int(lot_raw) if lot_raw.isdigit() else None

        owner_raw = (form_data.get("owner_id") or "").strip()
        owner_id = int(owner_raw) if owner_raw.isdigit() else None

        # If a lot is set but no owner picked, derive the current owner from the lot.
        if lot_id is not None and owner_id is None:
            owner_id = self._current_owner_for_lot(lot_id)

        category_raw = (form_data.get("category_id") or "").strip()
        category_id = int(category_raw) if category_raw.isdigit() else None

        ref = (form_data.get("reference_number") or "").strip() or None
        charge_type = (form_data.get("charge_type") or "").strip() or None
        memo = (form_data.get("memo") or "").strip() or None

        # Specific-charges mode — multi-checkbox list of assessment ids.
        # Stored as JSON in apply_to_assessment_ids so the order the
        # treasurer ticked them is preserved (relevant when a check
        # crosses an assessment boundary).
        apply_ids_str: str | None = None
        if apply_to_assessment_ids:
            cleaned = [int(x) for x in apply_to_assessment_ids if str(x).isdigit()]
            if cleaned:
                if lot_id is None:
                    raise ValidationError(
                        "Specific charges require a lot. Pick a lot or untick all charges."
                    )
                apply_ids_str = json.dumps(cleaned)

        return dict(
            classification_date=classification_date,
            expected_deposit_date=expected,
            bank_account_id=int(bank_raw),
            lot_id=lot_id,
            owner_id=owner_id,
            amount=str(amount),
            payment_method=payment_method,
            reference_number=ref,
            category_id=category_id,
            charge_type=charge_type,
            memo=memo,
            apply_to_assessment_ids=apply_ids_str,
            created_by_user_id=None,
        )

    # ── Manual match / unmatch ───────────────────────────────────────

    def render_match_page(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        pc_id: int,
        flash_message: str = "",
        error_message: str = "",
    ) -> PageResponse:
        pc = self.repo.get(pc_id)
        if pc is None:
            return PageResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body_html="<h1>Pending classification not found</h1>",
            )

        # Build context: PC details, current match (if any), candidate list
        pc_dict = dict(pc)
        bank_row = self.conn.execute(
            "SELECT id, account_name, account_last4 FROM bank_accounts WHERE id = ?",
            (pc["bank_account_id"],),
        ).fetchone()
        pc_dict["bank_account_name"] = bank_row["account_name"] if bank_row else ""
        pc_dict["bank_account_last4"] = bank_row["account_last4"] if bank_row else ""

        if pc["lot_id"]:
            lot_row = self.conn.execute(
                "SELECT lot_number FROM lots WHERE id = ?", (pc["lot_id"],)
            ).fetchone()
            pc_dict["lot_number"] = lot_row["lot_number"] if lot_row else ""
        else:
            pc_dict["lot_number"] = ""

        if pc["owner_id"]:
            owner_row = self.conn.execute(
                "SELECT display_name FROM owners WHERE id = ?", (pc["owner_id"],)
            ).fetchone()
            pc_dict["owner_name"] = owner_row["display_name"] if owner_row else ""
        else:
            pc_dict["owner_name"] = ""

        current_match = self.matcher.get_matched_bank_tx(pc_id)
        candidates = self.matcher.find_candidates_for_classification(pc_id)

        ctx = {
            **_BASE_CTX,
            "heading": "Match to a Bank Transaction",
            "breadcrumb": "Homeowners · Pending Classifications · Match",
            "parent_url": "/pending-classifications",
            "org": org or {},
            "theme": theme,
            "pc": pc_dict,
            "current_match": current_match,
            "candidates": [
                {
                    "bank_transaction_id": c.bank_transaction_id,
                    "transaction_date": c.transaction_date,
                    "description": c.description,
                    "amount": c.amount,
                }
                for c in candidates
            ],
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return PageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.MATCH_TEMPLATE, ctx),
        )

    def handle_match(
        self, *, pc_id: int, bank_transaction_id: int
    ) -> tuple[str | None, PageResponse | None]:
        try:
            self.matcher.link(
                pc_id=pc_id,
                bank_transaction_id=bank_transaction_id,
                commit=True,
            )
        except ValidationError as exc:
            return (
                f"/pending-classifications/{pc_id}/match"
                f"?err={str(exc).replace(' ', '+')}",
                None,
            )
        except Exception:
            self.conn.rollback()
            raise
        return (
            f"/pending-classifications?msg=Matched+to+bank+transaction+{bank_transaction_id}.",
            None,
        )

    def handle_unmatch(self, *, pc_id: int) -> tuple[str | None, PageResponse | None]:
        try:
            self.matcher.unlink(pc_id=pc_id, commit=True)
        except ValidationError as exc:
            return (
                f"/pending-classifications?err={str(exc).replace(' ', '+')}",
                None,
            )
        except Exception:
            self.conn.rollback()
            raise
        return ("/pending-classifications?msg=Unmatched.", None)

    # ── Post (dry-run + commit) ──────────────────────────────────────

    def render_post_page(
        self,
        *,
        org: dict[str, object] | None,
        theme: str,
        bank_account_id: int | None = None,
        flash_message: str = "",
        error_message: str = "",
    ) -> PageResponse:
        previews = self.poster.preview_all_matched(bank_account_id=bank_account_id)
        bank_accounts = self.conn.execute(
            "SELECT id, account_name, account_last4 FROM bank_accounts "
            "WHERE active_flag = 1 OR active_flag IS NULL "
            "ORDER BY account_name COLLATE NOCASE"
        ).fetchall()

        rows = [
            {
                "pc_id": p.pc_id,
                "classification_date": p.classification_date,
                "payment_date": p.payment_date,
                "bank_account_id": p.bank_account_id,
                "bank_account_name": p.bank_account_name,
                "lot_number": p.lot_number,
                "owner_name": p.owner_name,
                "amount": str(p.amount),
                "payment_method": p.payment_method,
                "drain_label": (
                    f"specific: {', '.join(str(i) for i in p.explicit_assessment_ids)}"
                    if p.explicit_assessment_ids
                    else ", ".join(p.charge_types)
                ),
                "matched_bank_transaction_id": p.matched_bank_transaction_id,
                "can_post": p.can_post,
                "block_reason": p.block_reason,
            }
            for p in previews
        ]
        postable_count = sum(1 for r in rows if r["can_post"])

        ctx = {
            **_BASE_CTX,
            "heading": "Post Matched Classifications",
            "breadcrumb": "Homeowners · Pending Classifications · Post",
            "parent_url": "/pending-classifications",
            "org": org or {},
            "theme": theme,
            "rows": rows,
            "postable_count": postable_count,
            "bank_accounts": [dict(b) for b in bank_accounts],
            "selected_bank_account_id": bank_account_id,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return PageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.POST_TEMPLATE, ctx),
        )

    def handle_post_one(self, *, pc_id: int) -> tuple[str | None, PageResponse | None]:
        try:
            self.poster.post(pc_id)
        except ValidationError as exc:
            return (
                f"/pending-classifications/post?err={str(exc).replace(' ', '+')}",
                None,
            )
        except Exception:
            self.conn.rollback()
            raise
        return (
            f"/pending-classifications?msg=Posted+classification+{pc_id}.",
            None,
        )

    def handle_reverse_post(
        self, *, pc_id: int
    ) -> tuple[str | None, PageResponse | None]:
        try:
            self.poster.reverse(pc_id)
        except ValidationError as exc:
            return (
                f"/pending-classifications?err={str(exc).replace(' ', '+')}",
                None,
            )
        except Exception:
            self.conn.rollback()
            raise
        return (
            f"/pending-classifications?msg=Reversed+post+for+classification+{pc_id}.+It+is+back+to+MATCHED.",
            None,
        )

    def handle_post_all(
        self, *, bank_account_id: int | None = None
    ) -> tuple[str | None, PageResponse | None]:
        try:
            result = self.poster.post_all_matched(bank_account_id=bank_account_id)
        except Exception:
            self.conn.rollback()
            raise

        msg_parts = []
        if result.posted:
            msg_parts.append(f"Posted {len(result.posted)}")
        if result.skipped:
            msg_parts.append(f"skipped {len(result.skipped)}")
        msg = ", ".join(msg_parts) or "Nothing to post"
        if result.skipped and not result.posted:
            return (
                f"/pending-classifications/post?err={msg.replace(' ', '+')}",
                None,
            )
        return (
            f"/pending-classifications?msg={msg.replace(' ', '+')}.",
            None,
        )

    def _current_owner_for_lot(self, lot_id: int) -> int | None:
        row = self.conn.execute(
            """
            SELECT owner_id
            FROM lot_ownership
            WHERE lot_id = ? AND end_date IS NULL
            ORDER BY id ASC
            LIMIT 1
            """,
            (lot_id,),
        ).fetchone()
        return int(row["owner_id"]) if row else None

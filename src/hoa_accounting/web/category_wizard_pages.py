"""Categories Interview — turn HOA-specific Yes/No answers into a baseline
set of Income & Expense categories.

The interview content lives in the existing ``wizard_groups`` and
``wizard_options`` tables (originally built for the Chart-of-Accounts
wizard, now repurposed for categories).

The flow is intentionally one page: every group is shown at once, with a
single Save button that creates / activates / deactivates categories in a
single pass.

Idempotency rules
-----------------
* A checked option whose ``code`` is already in ``categories`` is left as-is
  (and re-activated if previously deactivated).
* A checked option whose ``code`` is **not** in ``categories`` is inserted.
* An *un*-checked option whose ``code`` is in ``categories`` AND has no
  transactions referencing it is deactivated. If transactions reference it,
  the row is left alone — the user can deactivate manually if they really
  mean it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from hoa_accounting.web.template_engine import render_template

# ── Step → group → category-type / fund-code mapping ──────────────────────
#
# The wizard steps were originally:
#   step 1  funds              (drives fund_code only — NOT categories)
#   step 2  income             → INCOME, OPERATING
#   step 3  amenities          → EXPENSE, OPERATING
#   step 4  expense buckets    → EXPENSE, OPERATING
#   step 5  reserves           → EXPENSE, RESERVE
#
# step 1 is rendered for the user as informational checkboxes that flip the
# fund_code on subsequent option rows (RESERVE / SPECIAL only).

_INCOME_GROUPS = {"income"}
_RESERVE_GROUPS = {"reserves"}


@dataclass(frozen=True)
class CategoryWizardResponse:
    status_code: int
    body_html: str


class CategoryWizardPages:
    TEMPLATE = "category_wizard.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── GET ───────────────────────────────────────────────────────────
    def render(
        self,
        *,
        org: dict[str, Any] | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> CategoryWizardResponse:
        # Pull groups (skip step 1 — funds — it's not category-bearing).
        groups = list(self.conn.execute("""SELECT step_number, group_id, label
                 FROM wizard_groups
                WHERE is_active = 1 AND step_number > 1
                ORDER BY step_number, sort_order, group_id""").fetchall())
        existing = {
            r[0].upper(): bool(r[1])
            for r in self.conn.execute(
                "SELECT code, active_flag FROM categories"
            ).fetchall()
        }

        steps: dict[int, list[Any]] = {}
        for g in groups:
            options = list(
                self.conn.execute(
                    """SELECT option_id, label, description, is_always
                     FROM wizard_options
                    WHERE is_active = 1
                      AND group_id = ?
                      AND step_number = ?
                      AND option_id != '_always'
                    ORDER BY sort_order, option_id""",
                    (g["group_id"], g["step_number"]),
                ).fetchall()
            )
            opt_dicts = []
            for o in options:
                code = o["option_id"].upper()
                opt_dicts.append(
                    {
                        "option_id": o["option_id"],
                        "code": code,
                        "label": o["label"],
                        "description": o["description"] or "",
                        # Pre-check: existing+active OR brand-new (default ON for
                        # first-time users, so they get a useful starter set).
                        "checked": existing.get(code, True),
                        "already_exists": code in existing,
                    }
                )
            if opt_dicts:
                steps.setdefault(g["step_number"], []).append(
                    {
                        "group_id": g["group_id"],
                        "label": g["label"],
                        "category_type": (
                            "INCOME" if g["group_id"] in _INCOME_GROUPS else "EXPENSE"
                        ),
                        "fund_code": (
                            "RESERVE"
                            if g["group_id"] in _RESERVE_GROUPS
                            else "OPERATING"
                        ),
                        "options": opt_dicts,
                    }
                )

        ordered_steps = [
            {"step_number": s, "groups": steps[s]} for s in sorted(steps.keys())
        ]
        ctx = {
            "heading": "Categories Interview",
            "breadcrumb": "Getting Started",
            "parent_url": "/",
            "org": org or {},
            "theme": theme,
            "active_nav": "getting-started",
            "page_key": "categories-interview",
            "steps": ordered_steps,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        status = HTTPStatus.BAD_REQUEST if error_message else HTTPStatus.OK
        return CategoryWizardResponse(
            status_code=status,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    # ── POST ──────────────────────────────────────────────────────────
    def handle_submit(
        self,
        *,
        selected_codes: list[str],
    ) -> tuple[str, str]:
        """Apply the checkbox state from the form to the categories table.

        Returns (redirect_url, flash_message).
        """
        selected = {c.upper() for c in selected_codes}

        # Re-pull every option from the catalog; what isn't in `selected`
        # gets deactivated (when safe). Skip the funds step.
        catalog = list(
            self.conn.execute(
                """SELECT wo.option_id, wo.label, wo.description, wo.sort_order,
                      wg.group_id
                 FROM wizard_options wo
                 JOIN wizard_groups  wg ON wg.group_id = wo.group_id
                                       AND wg.step_number = wo.step_number
                WHERE wo.is_active = 1 AND wg.is_active = 1
                  AND wo.step_number > 1
                  AND wo.option_id != '_always'"""
            ).fetchall()
        )

        # Cache existing categories by code.
        existing = {
            r["code"].upper(): r
            for r in self.conn.execute(
                "SELECT id, code, active_flag FROM categories"
            ).fetchall()
        }

        added = reactivated = deactivated = unchanged = locked = 0

        for opt in catalog:
            code = opt["option_id"].upper()
            group_id = opt["group_id"]
            cat_type = "INCOME" if group_id in _INCOME_GROUPS else "EXPENSE"
            fund_code = "RESERVE" if group_id in _RESERVE_GROUPS else "OPERATING"

            if code in selected:
                if code in existing:
                    if not existing[code]["active_flag"]:
                        self.conn.execute(
                            "UPDATE categories SET active_flag = 1 WHERE id = ?",
                            (existing[code]["id"],),
                        )
                        reactivated += 1
                    else:
                        unchanged += 1
                else:
                    self.conn.execute(
                        """INSERT INTO categories
                           (code, name, category_type, fund_code,
                            group_name, sort_order, active_flag, description)
                           VALUES (?,?,?,?,?,?,1,?)""",
                        (
                            code,
                            opt["label"],
                            cat_type,
                            fund_code,
                            group_id,
                            int(opt["sort_order"] or 0),
                            opt["description"] or "",
                        ),
                    )
                    added += 1
            else:
                # Un-checked: deactivate only when safe.
                if code in existing and existing[code]["active_flag"]:
                    if self._has_transactions(int(existing[code]["id"])):
                        locked += 1
                    else:
                        self.conn.execute(
                            "UPDATE categories SET active_flag = 0 WHERE id = ?",
                            (existing[code]["id"],),
                        )
                        deactivated += 1

        self.conn.commit()
        parts = []
        if added:
            parts.append(f"{added} added")
        if reactivated:
            parts.append(f"{reactivated} re-activated")
        if deactivated:
            parts.append(f"{deactivated} deactivated")
        if unchanged:
            parts.append(f"{unchanged} unchanged")
        if locked:
            parts.append(f"{locked} kept (in use)")
        msg = "Categories saved · " + (", ".join(parts) if parts else "no changes")
        return ("/categories?msg=" + msg.replace(" ", "+"), msg)

    # ── Helpers ───────────────────────────────────────────────────────
    _REF_TABLES = (
        "assessments",
        "payments",
        "deposit_batches",
        "vendor_bills",
        "income_batches",
        "owner_adjustments",
        "assessment_rules",
        "reserve_transfers",
        "bank_transactions",
        "bank_transaction_rules",
        "budget_lines",
    )

    def _has_transactions(self, category_id: int) -> bool:
        for t in self._REF_TABLES:
            row = self.conn.execute(
                f"SELECT 1 FROM {t} WHERE category_id = ? LIMIT 1",
                (category_id,),
            ).fetchone()
            if row:
                return True
        return False

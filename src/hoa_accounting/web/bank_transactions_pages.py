"""Pending Validation page for canonical bank_transactions.

Shows every bank_transactions row with ``validation_status = 'UNVALIDATED'``
and lets the user either accept its proposed rule match, pick a category
(posting a one-off ledger record), link to an existing ledger record, or
ignore the line.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.services.non_dues_income_service import IncomeRow
from hoa_accounting.web.bank_statement_pages import BankStatementPages
from hoa_accounting.web.template_engine import render_template


# Candidate search window for "Link to existing" — wide enough to catch a
# deposit recorded a few days before the bank cleared it, narrow enough to
# not drown the user in unrelated rows.
_LINK_DATE_WINDOW_DAYS = 14

# Valid ledger_source_type values for manual linking. Matches the
# polymorphic vocabulary in reconciliation_clears.
_LINKABLE_SOURCE_TYPES = {"PAYMENT", "INCOME_BATCH", "BILL_PAYMENT"}


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


class BankTransactionsPages:
    """Render the pending-validation queue and handle row-level actions."""

    TEMPLATE = "bank_transactions_pending.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        # The ledger-posting logic (_apply_rule) still lives on
        # BankStatementPages — reuse it rather than duplicate.
        self._bsp = BankStatementPages(conn)

    # ── Rendering ────────────────────────────────────────────────────────

    def render_pending(
        self,
        *,
        org: dict,
        theme: str,
        bank_account_id: int | None = None,
        flash_message: str = "",
        error_message: str = "",
        show_ignored: bool = False,
        import_message: str = "",
        import_warnings: list[str] | None = None,
    ) -> PageResponse:
        accounts = self._conn.execute(
            "SELECT id, account_name, account_last4 "
            "FROM bank_accounts ORDER BY account_name"
        ).fetchall()

        params: list = []
        if show_ignored:
            where = "WHERE bt.validation_status IN ('UNVALIDATED', 'IGNORED')"
        else:
            where = "WHERE bt.validation_status = 'UNVALIDATED'"
        if bank_account_id:
            where += " AND bt.bank_account_id = ?"
            params.append(bank_account_id)

        rows = self._conn.execute(
            f"""
            SELECT bt.id, bt.bank_account_id, bt.transaction_date,
                   bt.description, bt.memo, bt.amount, bt.transaction_type,
                   bt.external_reference, bt.dedup_key, bt.created_at,
                   bt.match_type, bt.rule_id, bt.validation_status,
                   bt.matched_source_type, bt.matched_source_id,
                   ba.account_name, ba.account_last4,
                   r.rule_name, r.action_type, r.category_id,
                   c.name AS category_name
            FROM bank_transactions bt
            JOIN bank_accounts ba ON ba.id = bt.bank_account_id
            LEFT JOIN bank_transaction_rules r ON r.id = bt.rule_id
            LEFT JOIN categories c ON c.id = r.category_id
            {where}
            ORDER BY bt.transaction_date DESC, bt.id DESC
            """,
            params,
        ).fetchall()

        ignored_count = int(self._conn.execute(
            "SELECT COUNT(*) FROM bank_transactions WHERE validation_status = 'IGNORED'"
            + (" AND bank_account_id = ?" if bank_account_id else ""),
            ([bank_account_id] if bank_account_id else []),
        ).fetchone()[0])

        counts = self._conn.execute(
            """
            SELECT bt.bank_account_id, COUNT(*) AS n
            FROM bank_transactions bt
            WHERE bt.validation_status = 'UNVALIDATED'
            GROUP BY bt.bank_account_id
            """,
        ).fetchall()
        count_by_account = {r["bank_account_id"]: r["n"] for r in counts}
        total_pending = sum(count_by_account.values())

        # Count rows with a usable proposed match (so the page can show the
        # Dry Run / Accept All buttons only when there's something to act on).
        # Two literal query strings rather than f-string interpolation so the
        # SQL surface is statically auditable.
        if bank_account_id:
            acceptable_count = int(self._conn.execute(
                "SELECT COUNT(*) FROM bank_transactions bt "
                "WHERE bt.validation_status = 'UNVALIDATED' "
                "  AND bt.match_type IN ('RULE','SOURCE','BATCH') "
                "  AND bt.bank_account_id = ?",
                (bank_account_id,),
            ).fetchone()[0])
        else:
            acceptable_count = int(self._conn.execute(
                "SELECT COUNT(*) FROM bank_transactions bt "
                "WHERE bt.validation_status = 'UNVALIDATED' "
                "  AND bt.match_type IN ('RULE','SOURCE','BATCH')"
            ).fetchone()[0])

        ctx = {
            "heading": "Pending Validation",
            "org": org,
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "bank-pending",
            "breadcrumb": "Money In · Bank Data",
            "parent_url": "/",
            "accounts": [dict(a) for a in accounts],
            "selected_bank_account_id": bank_account_id,
            "rows": [dict(r) for r in rows],
            "total_pending": total_pending,
            "count_by_account": count_by_account,
            "acceptable_count": acceptable_count,
            "ignored_count": ignored_count,
            "show_ignored": show_ignored,
            "flash_message": flash_message,
            "error_message": error_message,
            "import_message": import_message,
            "import_warnings": import_warnings or [],
        }
        status = 400 if error_message else 200
        return PageResponse(
            status_code=status,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    # ── Actions ──────────────────────────────────────────────────────────

    def handle_accept(self, bank_txn_id: int) -> tuple[str, str]:
        """Post a ledger record for a rule-matched bank transaction and
        mark it validated. No-ops (and reports) for rows without a usable
        rule match.

        Returns ``(redirect_url, flash_message)``.
        """
        row = self._conn.execute(
            """
            SELECT bt.id, bt.bank_account_id, bt.transaction_date,
                   bt.description, bt.memo, bt.amount, bt.match_type,
                   bt.rule_id, bt.validation_status,
                   r.action_type, r.category_id, r.lot_id, r.vendor_id,
                   r.default_memo
            FROM bank_transactions bt
            LEFT JOIN bank_transaction_rules r ON r.id = bt.rule_id
            WHERE bt.id = ?
            """,
            (bank_txn_id,),
        ).fetchone()

        back = "/bank-transactions/pending"
        if row is None:
            return back, "Transaction not found."
        if row["validation_status"] != "UNVALIDATED":
            return back, "Already validated or ignored — no action taken."

        match_type = row["match_type"]

        # SOURCE / BATCH matches were pre-stamped at import time and link
        # to an existing ledger record. Accepting them just transitions
        # the row to VALIDATED — no new posting is needed.
        if match_type in ("SOURCE", "BATCH"):
            current = self._conn.execute(
                "SELECT matched_source_type, matched_source_id "
                "FROM bank_transactions WHERE id = ?",
                (bank_txn_id,),
            ).fetchone()
            if not current or not current["matched_source_type"]:
                return back, "Match metadata is missing — re-run validation first."
            self._conn.execute(
                "UPDATE bank_transactions SET validation_status = 'VALIDATED' WHERE id = ?",
                (bank_txn_id,),
            )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO bank_transaction_links
                    (bank_transaction_id, ledger_source_type, ledger_source_id, link_source)
                VALUES (?, ?, ?, ?)
                """,
                (bank_txn_id, current["matched_source_type"],
                 int(current["matched_source_id"]), match_type),
            )
            self._conn.commit()
            return back, f"Accepted — linked to {current['matched_source_type'].lower()} #{current['matched_source_id']}."

        if match_type != "RULE" or not row["rule_id"]:
            return back, "No rule match on this transaction. Pick a category or link an existing ledger record."

        result = self._bsp._apply_rule(
            dict(row),
            dict(row),
            bank_account_id=int(row["bank_account_id"]),
        )
        if result is None:
            return back, (
                "Rule could not be applied — check that the rule has the "
                "required vendor, category, or lot and that the amount sign "
                "matches the action type."
            )

        source_type, source_id = result
        self._conn.execute(
            """
            UPDATE bank_transactions
               SET matched_source_type = ?, matched_source_id = ?,
                   validation_status = 'VALIDATED'
             WHERE id = ?
            """,
            (source_type, int(source_id), bank_txn_id),
        )
        self._conn.execute(
            """
            INSERT OR IGNORE INTO bank_transaction_links
                (bank_transaction_id, ledger_source_type, ledger_source_id,
                 link_source, rule_id)
            VALUES (?, ?, ?, 'RULE', ?)
            """,
            (bank_txn_id, source_type, int(source_id), int(row["rule_id"])),
        )
        # Bump the rule's confirmed-matches counter; promote to auto_post
        # once the user has signed off on enough of its matches.
        self._conn.execute(
            """
            UPDATE bank_transaction_rules
               SET confirmed_matches = confirmed_matches + 1,
                   confidence_mode = CASE
                       WHEN confirmed_matches + 1 >= auto_post_after_n
                           THEN 'auto_post'
                       ELSE confidence_mode
                   END
             WHERE id = ?
            """,
            (int(row["rule_id"]),),
        )
        self._conn.commit()
        return back, f"Accepted — posted {source_type.lower()} #{source_id}."

    # ── Classify screen (Pick Category / Link Existing) ─────────────────

    def _get_txn(self, bank_txn_id: int) -> dict | None:
        row = self._conn.execute(
            """
            SELECT bt.*, ba.account_name, ba.account_last4
            FROM bank_transactions bt
            JOIN bank_accounts ba ON ba.id = bt.bank_account_id
            WHERE bt.id = ?
            """,
            (bank_txn_id,),
        ).fetchone()
        return dict(row) if row else None

    def _linked_source_ids(self, source_type: str) -> set[int]:
        """Source ids already linked to some bank transaction — hide them
        from the candidate list so two bank lines don't claim one ledger
        record."""
        rows = self._conn.execute(
            "SELECT ledger_source_id FROM bank_transaction_links WHERE ledger_source_type = ?",
            (source_type,),
        ).fetchall()
        return {int(r["ledger_source_id"]) for r in rows}

    def _link_candidates(self, txn: dict) -> list[dict]:
        """Return ledger records that plausibly correspond to ``txn``.

        Match rule: same bank account, same absolute amount, posting date
        within ±_LINK_DATE_WINDOW_DAYS. Sign decides which tables to search
        (deposits → PAYMENT / INCOME_BATCH; debits → BILL_PAYMENT).
        """
        amount = Decimal(str(txn["amount"]))
        abs_amt = str(abs(amount))
        bank_id = int(txn["bank_account_id"])
        try:
            txn_date = date.fromisoformat(str(txn["transaction_date"]))
        except ValueError:
            return []
        lo = (txn_date - timedelta(days=_LINK_DATE_WINDOW_DAYS)).isoformat()
        hi = (txn_date + timedelta(days=_LINK_DATE_WINDOW_DAYS)).isoformat()

        candidates: list[dict] = []

        if amount > 0:
            linked_payments = self._linked_source_ids("PAYMENT")
            for r in self._conn.execute(
                """
                SELECT p.id, p.payment_date AS dt, p.amount, p.receipt_number,
                       o.first_name || ' ' || o.last_name AS owner_name
                FROM payments p
                LEFT JOIN owners o ON o.id = p.owner_id
                WHERE p.bank_account_id = ?
                  AND ABS(CAST(p.amount AS REAL)) = ABS(CAST(? AS REAL))
                  AND p.payment_date BETWEEN ? AND ?
                ORDER BY p.payment_date DESC
                LIMIT 20
                """,
                (bank_id, abs_amt, lo, hi),
            ).fetchall():
                if int(r["id"]) in linked_payments:
                    continue
                candidates.append({
                    "source_type": "PAYMENT",
                    "source_id": int(r["id"]),
                    "date": r["dt"],
                    "amount": r["amount"],
                    "label": f"Payment #{r['receipt_number'] or r['id']}"
                             + (f" — {r['owner_name']}" if r["owner_name"] else ""),
                })

            linked_batches = self._linked_source_ids("INCOME_BATCH")
            for r in self._conn.execute(
                """
                SELECT id, posting_date AS dt, total_amount AS amount,
                       income_description
                FROM income_batches
                WHERE bank_account_id = ?
                  AND ABS(CAST(total_amount AS REAL)) = ABS(CAST(? AS REAL))
                  AND posting_date BETWEEN ? AND ?
                ORDER BY posting_date DESC
                LIMIT 20
                """,
                (bank_id, abs_amt, lo, hi),
            ).fetchall():
                if int(r["id"]) in linked_batches:
                    continue
                candidates.append({
                    "source_type": "INCOME_BATCH",
                    "source_id": int(r["id"]),
                    "date": r["dt"],
                    "amount": r["amount"],
                    "label": f"Income #{r['id']} — {r['income_description'] or ''}",
                })
        else:
            linked_bps = self._linked_source_ids("BILL_PAYMENT")
            for r in self._conn.execute(
                """
                SELECT bp.id, bp.payment_date AS dt, bp.amount, bp.check_number,
                       v.vendor_name
                FROM bill_payments bp
                LEFT JOIN vendor_bills vb ON vb.id = bp.vendor_bill_id
                LEFT JOIN vendors v ON v.id = vb.vendor_id
                WHERE bp.bank_account_id = ?
                  AND ABS(CAST(bp.amount AS REAL)) = ABS(CAST(? AS REAL))
                  AND bp.payment_date BETWEEN ? AND ?
                ORDER BY bp.payment_date DESC
                LIMIT 20
                """,
                (bank_id, abs_amt, lo, hi),
            ).fetchall():
                if int(r["id"]) in linked_bps:
                    continue
                candidates.append({
                    "source_type": "BILL_PAYMENT",
                    "source_id": int(r["id"]),
                    "date": r["dt"],
                    "amount": r["amount"],
                    "label": (f"Bill payment #{r['check_number'] or r['id']}"
                              + (f" — {r['vendor_name']}" if r["vendor_name"] else "")),
                })

        return candidates

    def render_classify(
        self,
        *,
        bank_txn_id: int,
        org: dict,
        theme: str,
        error_message: str = "",
    ) -> PageResponse:
        txn = self._get_txn(bank_txn_id)
        if txn is None:
            return PageResponse(
                status_code=404,
                body_html=render_template("bank_transactions_pending.html", {
                    "org": org, "theme": theme, "active_nav": "transactions",
                    "page_key": "bank-pending", "accounts": [], "rows": [],
                    "total_pending": 0, "count_by_account": {},
                    "error_message": "Transaction not found.",
                    "flash_message": "", "selected_bank_account_id": None,
                    "breadcrumb": "Money In · Bank Data", "parent_url": "/",
                    "heading": "Pending Validation",
                }),
            )

        categories = self._conn.execute(
            """
            SELECT id, code, name, category_type, group_name
            FROM categories
            WHERE active_flag = 1 AND category_type IN ('INCOME', 'EXPENSE')
            ORDER BY category_type, sort_order, name
            """
        ).fetchall()
        vendors = self._conn.execute(
            "SELECT id, vendor_name FROM vendors WHERE active_flag = 1 ORDER BY vendor_name COLLATE NOCASE"
        ).fetchall()
        # Lots with first owner alphabetically (last, first) for the
        # owner-payment branch ("HOA Dues" / "Late Fees" / "Resale Fee").
        lots = self._conn.execute(
            """
            SELECT
                l.id,
                l.lot_number,
                COALESCE(
                    NULLIF(TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,'')), ''),
                    o.display_name, ''
                ) AS owner_name
            FROM lots l
            LEFT JOIN lot_ownership lo
                   ON lo.id = (
                        SELECT lo2.id FROM lot_ownership lo2
                        JOIN owners o2 ON o2.id = lo2.owner_id
                        WHERE lo2.lot_id = l.id AND lo2.end_date IS NULL
                        ORDER BY o2.last_name COLLATE NOCASE,
                                 o2.first_name COLLATE NOCASE,
                                 o2.display_name COLLATE NOCASE
                        LIMIT 1
                   )
            LEFT JOIN owners o ON o.id = lo.owner_id
            WHERE l.active_flag = 1
            ORDER BY l.lot_number
            """
        ).fetchall()

        amount = Decimal(str(txn["amount"]))
        is_income = amount > 0
        candidates = self._link_candidates(txn)

        ctx = {
            "heading": "Classify Transaction",
            "org": org,
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "bank-pending",
            "breadcrumb": "Money In · Bank Data · Pending Validation",
            "parent_url": "/bank-transactions/pending",
            "txn": txn,
            "is_income": is_income,
            "categories": [dict(c) for c in categories],
            "vendors": [dict(v) for v in vendors],
            "lots": [dict(l) for l in lots],
            "candidates": candidates,
            "error_message": error_message,
        }
        status = 400 if error_message else 200
        return PageResponse(
            status_code=status,
            body_html=render_template("bank_transaction_classify.html", ctx),
        )

    def handle_pick_category(
        self,
        bank_txn_id: int,
        *,
        lines: list[tuple[int, Decimal]],
        vendor_id: int | None,
        lot_id: int | None,
        memo: str,
    ) -> tuple[str, str]:
        """Post one or more ledger records for this bank line. Each line is
        (category_id, amount); their sum must equal the bank line's absolute
        amount (hard block on mismatch).

        Routing:
          - amount > 0 + owner-payment category (DUES/LATE_FEE/RESALE_FEE):
            single line, drains the lot's open assessments. Synthetic
            deposit_batch is created.
          - amount > 0 otherwise: N income_batches sharing one deposit_batch.
          - amount < 0: N vendor_bills + N bill_payments to the rule's vendor.
        """
        back = f"/bank-transactions/{bank_txn_id}/classify"
        txn = self._get_txn(bank_txn_id)
        if txn is None:
            return "/bank-transactions/pending", "Transaction not found."
        if txn["validation_status"] != "UNVALIDATED":
            return "/bank-transactions/pending", "Already validated or ignored."
        if not lines:
            return back, "Pick at least one category."

        amount = Decimal(str(txn["amount"]))
        target = abs(amount)
        line_sum = sum((amt for _, amt in lines), Decimal("0.00"))
        if abs(line_sum - target) >= Decimal("0.01"):
            return back, (f"Lines must sum to {target}; current total is "
                          f"{line_sum} (off by {target - line_sum}).")

        description = (memo or txn["description"] or "").strip()
        factory = ServiceFactory(self._conn)

        OWNER_PAYMENT_CODES = {"DUES", "LATE_FEE", "RESALE_FEE"}
        first_cat_id = int(lines[0][0])
        first_cat_row = self._conn.execute(
            "SELECT code FROM categories WHERE id = ?", (first_cat_id,)
        ).fetchone()
        first_code = (first_cat_row["code"] if first_cat_row else "").upper()

        # Owner payments are intrinsically single-line; the JS prevents
        # adding more, but enforce here too.
        if amount > 0 and first_code in OWNER_PAYMENT_CODES:
            if len(lines) != 1:
                return back, "Owner-payment categories (HOA Dues / Late Fees / Resale Fees) cannot be split."
            if not lot_id:
                return back, "Lot is required when the category is an owner charge."
            owner = self._conn.execute(
                """SELECT owner_id FROM lot_ownership
                   WHERE lot_id = ? AND end_date IS NULL
                   ORDER BY start_date DESC LIMIT 1""",
                (int(lot_id),),
            ).fetchone()
            if not owner:
                return back, "Selected lot has no current owner on record."

            batch_cur = self._conn.execute(
                """INSERT INTO deposit_batches
                   (deposit_date, bank_account_id, total_amount, notes)
                   VALUES (?, ?, ?, ?)""",
                (
                    txn["transaction_date"],
                    int(txn["bank_account_id"]),
                    str(amount),
                    f"ACH dues — {description}" if description else "ACH dues",
                ),
            )
            deposit_batch_id = int(batch_cur.lastrowid)

            charge_filter = ("RESALE_FEE",) if first_code == "RESALE_FEE" else ("DUES", "LATE_FEE")
            open_assess = [
                int(r[0]) for r in self._conn.execute(
                    """SELECT a.id FROM assessments a
                       WHERE a.lot_id = ?
                         AND a.charge_type IN ({}) AND a.status NOT IN ('PAID', 'VOID', 'WRITTEN_OFF')
                       ORDER BY a.due_date ASC, a.id ASC""".format(
                        ",".join("?" * len(charge_filter))
                    ),
                    (int(lot_id), *charge_filter),
                ).fetchall()
            ]
            payment = factory.payment_service().post_payment(
                entry_date=txn["transaction_date"],
                owner_id=int(owner["owner_id"]),
                amount=str(amount),
                description=description or "Owner payment (manual classify)",
                bank_account_id=int(txn["bank_account_id"]),
                payment_method="ACH",
                receipt_number=self._bsp._next_receipt_number(txn["transaction_date"]),
                apply_to_assessment_ids=open_assess,
            )
            self._conn.execute(
                "UPDATE payments SET deposit_batch_id = ? WHERE id = ?",
                (deposit_batch_id, payment.payment_id),
            )
            primary = ("PAYMENT", int(payment.payment_id))
            extra: list[tuple[str, int]] = []
        elif amount > 0:
            # Non-owner income — N lines, all on one deposit_batch so the
            # Deposits report sees the slip total.
            batch_cur = self._conn.execute(
                """INSERT INTO deposit_batches
                   (deposit_date, bank_account_id, total_amount, notes)
                   VALUES (?, ?, ?, ?)""",
                (
                    txn["transaction_date"],
                    int(txn["bank_account_id"]),
                    str(amount),
                    description or None,
                ),
            )
            deposit_batch_id = int(batch_cur.lastrowid)
            posted: list[tuple[str, int]] = []
            for cat_id, line_amt in lines:
                result = factory.non_dues_income_service().post_batch(
                    posting_date=txn["transaction_date"],
                    bank_account_id=int(txn["bank_account_id"]),
                    income_description=description or "Bank import",
                    rows=[IncomeRow(amount=str(line_amt), other_source="BANK")],
                    category_id=int(cat_id),
                    deposit_batch_id=deposit_batch_id,
                )
                posted.append(("INCOME_BATCH", int(result.income_batch_id)))
            primary = posted[0]
            extra = posted[1:]
        else:
            if not vendor_id:
                return back, "Vendor is required for expense transactions."
            posted = []
            for idx, (cat_id, line_amt) in enumerate(lines, start=1):
                invoice_number = (
                    f"BR-{str(txn['transaction_date']).replace('-', '')}"
                    f"-{int(bank_txn_id):06d}"
                    + (f"-L{idx}" if len(lines) > 1 else "")
                )
                bill = factory.vendor_bill_service().post_vendor_bill(
                    entry_date=txn["transaction_date"],
                    vendor_id=int(vendor_id),
                    amount=str(line_amt),
                    description=description,
                    invoice_number=invoice_number,
                    invoice_date=txn["transaction_date"],
                    category_id=int(cat_id),
                )
                vendor_payment = factory.vendor_payment_service().post_vendor_payment(
                    entry_date=txn["transaction_date"],
                    vendor_bill_id=bill.vendor_bill_id,
                    amount=str(line_amt),
                    description=description,
                    bank_account_id=int(txn["bank_account_id"]),
                )
                posted.append(("BILL_PAYMENT", int(vendor_payment.bill_payment_id)))
            primary = posted[0]
            extra = posted[1:]

        # Mark the bank line validated; primary record powers existing
        # views, extras live in bank_transaction_links so the full split
        # is auditable.
        self._conn.execute(
            """
            UPDATE bank_transactions
               SET matched_source_type = ?, matched_source_id = ?,
                   validation_status = 'VALIDATED'
             WHERE id = ?
            """,
            (primary[0], primary[1], bank_txn_id),
        )
        for st, sid in [primary, *extra]:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO bank_transaction_links
                    (bank_transaction_id, ledger_source_type, ledger_source_id,
                     link_source)
                VALUES (?, ?, ?, 'MANUAL')
                """,
                (bank_txn_id, st, sid),
            )
        self._conn.commit()
        n = len(lines)
        return "/bank-transactions/pending", (
            f"Posted {primary[0].lower()} #{primary[1]}"
            + (f" + {n - 1} additional split line(s)" if n > 1 else "")
            + "."
        )

    def handle_link_existing(
        self,
        bank_txn_id: int,
        *,
        source_type: str,
        source_id: int,
    ) -> tuple[str, str]:
        """Link an existing ledger record to this bank line instead of
        creating a new one. Validates type + amount/account consistency
        before writing."""
        back = f"/bank-transactions/{bank_txn_id}/classify"
        if source_type not in _LINKABLE_SOURCE_TYPES:
            return back, f"Unsupported link target: {source_type}."

        txn = self._get_txn(bank_txn_id)
        if txn is None:
            return "/bank-transactions/pending", "Transaction not found."
        if txn["validation_status"] != "UNVALIDATED":
            return "/bank-transactions/pending", "Already validated or ignored."

        # Verify the target exists on the same account. Amount-equality is
        # advisory (the user explicitly chose this row), so we skip that
        # check to allow small fee differences.
        table, date_col, amount_col = {
            "PAYMENT":      ("payments",       "payment_date", "amount"),
            "INCOME_BATCH": ("income_batches", "posting_date", "total_amount"),
            "BILL_PAYMENT": ("bill_payments",  "payment_date", "amount"),
        }[source_type]
        ledger = self._conn.execute(
            f"SELECT id, bank_account_id FROM {table} WHERE id = ?",
            (source_id,),
        ).fetchone()
        if not ledger or int(ledger["bank_account_id"]) != int(txn["bank_account_id"]):
            return back, "Selected record not found for this bank account."

        self._conn.execute(
            """
            UPDATE bank_transactions
               SET match_type = 'SOURCE',
                   matched_source_type = ?, matched_source_id = ?,
                   reconciliation_status = 'MATCHED',
                   validation_status = 'VALIDATED'
             WHERE id = ?
            """,
            (source_type, int(source_id), bank_txn_id),
        )
        self._conn.execute(
            """
            INSERT OR IGNORE INTO bank_transaction_links
                (bank_transaction_id, ledger_source_type, ledger_source_id,
                 link_source)
            VALUES (?, ?, ?, 'MANUAL')
            """,
            (bank_txn_id, source_type, int(source_id)),
        )
        self._conn.commit()
        return "/bank-transactions/pending", f"Linked to {source_type.lower()} #{source_id}."

    # ── Manual entry (grid) ──────────────────────────────────────────────

    def render_manual_entry(
        self,
        *,
        org: dict,
        theme: str,
        bank_account_id: int | None = None,
        error_message: str = "",
        flash_message: str = "",
    ) -> PageResponse:
        """Grid-style entry form for HOAs that don't receive bank files —
        they transcribe a monthly paper statement into rows instead.
        Submitted rows flow through the same ingest path as OFX/CSV so
        rules, dedup, and the Pending Validation queue all apply."""
        from hoa_accounting.web.bank_ingest import CANONICAL_TRN_TYPES

        accounts = self._conn.execute(
            "SELECT id, account_name, account_last4 "
            "FROM bank_accounts ORDER BY account_name"
        ).fetchall()

        ctx = {
            "heading": "Manual Bank Entry",
            "org": org,
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "bank-manual",
            "breadcrumb": "Money In · Bank Data",
            "parent_url": "/bank-transactions/pending",
            "accounts": [dict(a) for a in accounts],
            "selected_bank_account_id": bank_account_id,
            "trn_types": sorted(CANONICAL_TRN_TYPES),
            "error_message": error_message,
            "flash_message": flash_message,
        }
        status = 400 if error_message else 200
        return PageResponse(
            status_code=status,
            body_html=render_template("bank_transaction_manual.html", ctx),
        )

    def handle_manual_submit(
        self,
        *,
        bank_account_id: int,
        rows: list[dict],
        org: dict,
        theme: str,
    ) -> tuple[str, str]:
        """Convert the submitted grid rows into ``CanonicalBankTxn``
        records and feed them through ``_store_pending_batch`` so the
        manual-entry path produces the same audit trail and validation
        queue entries as a file import."""
        from datetime import datetime
        from hoa_accounting.web.bank_ingest import (
            CANONICAL_TRN_TYPES, CanonicalBankTxn, normalize_trn_type,
        )
        from hoa_accounting.web.bank_statement_pages import BankStatementPages

        ba = self._conn.execute(
            "SELECT id, account_name FROM bank_accounts WHERE id = ?",
            (bank_account_id,),
        ).fetchone()
        if ba is None:
            return "/bank-transactions/manual", "Bank account not found."

        canonical: list[CanonicalBankTxn] = []
        errors: list[str] = []
        for idx, r in enumerate(rows, start=1):
            date_str = (r.get("date") or "").strip()
            amount_str = (r.get("amount") or "").strip()
            description = (r.get("description") or "").strip()
            if not date_str and not amount_str and not description:
                # Blank grid row — skip silently so users can leave spares.
                continue
            try:
                posted = date.fromisoformat(date_str)
            except ValueError:
                errors.append(f"Row {idx}: invalid date '{date_str}' (use YYYY-MM-DD).")
                continue
            try:
                amount = Decimal(amount_str.replace(",", "").replace("$", ""))
            except (InvalidOperation, ValueError):
                errors.append(f"Row {idx}: invalid amount '{amount_str}'.")
                continue
            if not description:
                errors.append(f"Row {idx}: description is required.")
                continue
            trn_type = (r.get("transaction_type") or "").strip().upper()
            if trn_type and trn_type not in CANONICAL_TRN_TYPES:
                trn_type = normalize_trn_type(trn_type)
            elif not trn_type:
                trn_type = "CREDIT" if amount > 0 else "DEBIT"
            canonical.append(CanonicalBankTxn(
                posted_at=posted,
                amount=amount,
                description=description,
                memo=(r.get("memo") or "").strip(),
                transaction_type=trn_type,
                check_number=(r.get("check_number") or "").strip(),
                external_ref="",
                raw={"source": "manual"},
            ))

        if errors:
            return "/bank-transactions/manual", " ".join(errors)
        if not canonical:
            return "/bank-transactions/manual", "No rows to save — fill in at least one line."

        bsp = BankStatementPages(self._conn)
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        bsp._store_pending_batch(
            reconciliation_id=None,
            bank_account_id=int(bank_account_id),
            filename=f"manual-entry-{stamp}",
            file_format="MANUAL",
            file_bytes=b"",
            csv_col_map={},
            transactions=canonical,
            items=bsp._get_unmatched_items(int(bank_account_id)),
            batches=bsp._get_unmatched_batches(int(bank_account_id)),
            rules=bsp._load_rules(),
        )
        return (
            f"/bank-transactions/pending?bank_account_id={bank_account_id}"
            f"&msg=Added+{len(canonical)}+manual+transaction(s).",
            "",
        )

    def handle_revalidate(self, bank_account_id: int | None = None) -> tuple[str, str]:
        """Re-run rule + source + batch matching against all UNVALIDATED
        bank_transactions rows. Lets the user fix a rule and replay
        matches without re-importing the OFX file.
        """
        from datetime import datetime
        from decimal import Decimal as _D
        from hoa_accounting.web.bank_statement_import import (
            ParsedTransaction, apply_rules, match_transactions, find_batch_matches,
        )

        back = "/bank-transactions/pending"
        if bank_account_id:
            back += f"?bank_account_id={bank_account_id}"

        where = "validation_status = 'UNVALIDATED'"
        params: list[object] = []
        if bank_account_id:
            where += " AND bank_account_id = ?"
            params.append(bank_account_id)
        rows = self._conn.execute(
            f"""SELECT id, bank_account_id, transaction_date, description, memo,
                       amount, external_reference, transaction_type
                FROM bank_transactions
                WHERE {where}
                ORDER BY id""",
            params,
        ).fetchall()
        if not rows:
            return back, "Nothing to re-validate — no unvalidated transactions."

        # Group by bank_account so each account uses its own rule/item lists.
        by_ba: dict[int, list] = {}
        for r in rows:
            by_ba.setdefault(int(r["bank_account_id"]), []).append(r)

        # Clear existing claims on the rows we're about to re-match so the
        # candidate-batch / candidate-item queries see those slots as free.
        # Without this, a batch already claimed by one of the txns being
        # revalidated would be excluded from the candidate list and the
        # match would be destroyed instead of refreshed.
        ids_to_revalidate = [int(r["id"]) for r in rows]
        if ids_to_revalidate:
            placeholders = ",".join("?" * len(ids_to_revalidate))
            self._conn.execute(
                f"UPDATE bank_transactions "
                f"SET match_type = 'UNMATCHED', rule_id = NULL, "
                f"    matched_source_type = NULL, matched_source_id = NULL "
                f"WHERE id IN ({placeholders})",
                ids_to_revalidate,
            )

        rules = [dict(r) for r in self._conn.execute(
            "SELECT * FROM bank_transaction_rules WHERE active_flag = 1"
        ).fetchall()]

        updated = 0
        for ba_id, batch_rows in by_ba.items():
            txns = [
                ParsedTransaction(
                    transaction_date=datetime.strptime(str(r["transaction_date"]), "%Y-%m-%d").date(),
                    amount=_D(str(r["amount"])),
                    description=r["description"] or "",
                    memo=r["memo"] or "",
                    fitid=r["external_reference"] or "",
                    transaction_type=r["transaction_type"] or "",
                )
                for r in batch_rows
            ]
            items = self._bsp._get_unmatched_items(ba_id)
            batches = self._bsp._get_unmatched_batches(ba_id)

            rule_m = apply_rules(txns, rules, bank_account_id=ba_id)
            source_m = match_transactions(txns, items, skip_indices=set(rule_m.keys()))
            batch_m = find_batch_matches(
                txns, batches,
                skip_indices=set(rule_m.keys()) | set(source_m.keys()),
            )

            for idx, r in enumerate(batch_rows):
                if idx in rule_m:
                    rid = int(rule_m[idx]["id"])
                    self._conn.execute(
                        "UPDATE bank_transactions "
                        "SET match_type='RULE', rule_id=?, "
                        "    matched_source_type=NULL, matched_source_id=NULL "
                        "WHERE id=?",
                        (rid, int(r["id"])),
                    )
                    updated += 1
                elif idx in source_m:
                    st, sid = source_m[idx]
                    self._conn.execute(
                        "UPDATE bank_transactions "
                        "SET match_type='SOURCE', rule_id=NULL, "
                        "    matched_source_type=?, matched_source_id=? "
                        "WHERE id=?",
                        (st, int(sid), int(r["id"])),
                    )
                    updated += 1
                elif idx in batch_m:
                    self._conn.execute(
                        "UPDATE bank_transactions "
                        "SET match_type='BATCH', rule_id=NULL, "
                        "    matched_source_type='DEPOSIT_BATCH', matched_source_id=? "
                        "WHERE id=?",
                        (int(batch_m[idx]), int(r["id"])),
                    )
                    updated += 1
                else:
                    self._conn.execute(
                        "UPDATE bank_transactions "
                        "SET match_type='UNMATCHED', rule_id=NULL, "
                        "    matched_source_type=NULL, matched_source_id=NULL "
                        "WHERE id=?",
                        (int(r["id"]),),
                    )
        self._conn.commit()
        return back, f"Re-validated {len(rows)} transaction(s); {updated} now have a proposed match."

    # ── Dry Run (preview what Accept All would do) ─────────────────────

    def render_dry_run(
        self, *, org: dict, theme: str, bank_account_id: int | None = None
    ) -> PageResponse:
        """List every UNVALIDATED row with a proposed match — RULE / SOURCE /
        BATCH — and show what *would* happen if Accept were clicked on each.
        Read-only; no writes."""
        where = "bt.validation_status = 'UNVALIDATED'"
        params: list[object] = []
        if bank_account_id:
            where += " AND bt.bank_account_id = ?"
            params.append(bank_account_id)

        rows = self._conn.execute(
            f"""
            SELECT bt.id, bt.transaction_date, bt.amount, bt.description,
                   bt.match_type, bt.matched_source_type, bt.matched_source_id,
                   ba.account_name, ba.account_last4,
                   r.rule_name, r.action_type,
                   v.vendor_name, c.name AS category_name,
                   l.lot_number AS rule_lot_number,
                   db.deposit_date AS batch_date, db.total_amount AS batch_amount,
                   db.notes AS batch_notes
            FROM bank_transactions bt
            JOIN bank_accounts ba ON ba.id = bt.bank_account_id
            LEFT JOIN bank_transaction_rules r ON r.id = bt.rule_id
            LEFT JOIN vendors v ON v.id = r.vendor_id
            LEFT JOIN categories c ON c.id = r.category_id
            LEFT JOIN lots l ON l.id = r.lot_id
            LEFT JOIN deposit_batches db
                   ON bt.match_type = 'BATCH'
                  AND db.id = bt.matched_source_id
            WHERE {where}
            ORDER BY bt.transaction_date, bt.id
            """,
            params,
        ).fetchall()

        rule_rows: list[dict] = []
        source_rows: list[dict] = []
        batch_rows: list[dict] = []
        unmatched_rows: list[dict] = []
        for r in rows:
            d = dict(r)
            if r["match_type"] == "RULE":
                rule_rows.append(d)
            elif r["match_type"] == "SOURCE":
                source_rows.append(d)
            elif r["match_type"] == "BATCH":
                batch_rows.append(d)
            else:
                unmatched_rows.append(d)

        def _sum(rs: list[dict]) -> Decimal:
            return sum((Decimal(str(r["amount"])) for r in rs), Decimal("0"))

        accounts = self._conn.execute(
            "SELECT id, account_name, account_last4 FROM bank_accounts "
            "WHERE active_flag = 1 ORDER BY account_name COLLATE NOCASE"
        ).fetchall()

        ctx = {
            "heading": "Dry Run — what Accept All would do",
            "org": org, "theme": theme,
            "active_nav": "transactions",
            "page_key": "bank-pending",
            "breadcrumb": "Money In · Bank Data",
            "parent_url": "/bank-transactions/pending",
            "rule_rows": rule_rows,
            "source_rows": source_rows,
            "batch_rows": batch_rows,
            "unmatched_rows": unmatched_rows,
            "rule_total":   str(_sum(rule_rows)),
            "source_total": str(_sum(source_rows)),
            "batch_total":  str(_sum(batch_rows)),
            "net":          str(_sum(rule_rows) + _sum(source_rows) + _sum(batch_rows)),
            "accounts": [dict(a) for a in accounts],
            "selected_bank_account_id": bank_account_id,
            "acceptable_count": len(rule_rows) + len(source_rows) + len(batch_rows),
        }
        return PageResponse(200, render_template("bank_transactions_dry_run.html", ctx))

    # ── Accept All (bulk validate every matched row) ────────────────────

    def handle_accept_all(
        self, *, bank_account_id: int | None = None
    ) -> tuple[str, str]:
        """Run handle_accept on every UNVALIDATED row that has a usable
        match (RULE, SOURCE, BATCH). Skips UNMATCHED. Reports counts."""
        # Two literal query strings rather than f-string interpolation so the
        # SQL surface is statically auditable.
        if bank_account_id:
            ids = [
                int(r[0]) for r in self._conn.execute(
                    "SELECT id FROM bank_transactions "
                    "WHERE validation_status = 'UNVALIDATED' "
                    "  AND match_type IN ('RULE','SOURCE','BATCH') "
                    "  AND bank_account_id = ? "
                    "ORDER BY transaction_date, id",
                    (bank_account_id,),
                ).fetchall()
            ]
        else:
            ids = [
                int(r[0]) for r in self._conn.execute(
                    "SELECT id FROM bank_transactions "
                    "WHERE validation_status = 'UNVALIDATED' "
                    "  AND match_type IN ('RULE','SOURCE','BATCH') "
                    "ORDER BY transaction_date, id"
                ).fetchall()
            ]
        back = "/bank-transactions/pending"
        if bank_account_id:
            back += f"?bank_account_id={bank_account_id}"
        if not ids:
            return back, "Nothing to accept — no rows have a proposed match."

        accepted = 0
        skipped: list[str] = []
        for tid in ids:
            _, msg = self.handle_accept(tid)
            if msg.lower().startswith("accepted"):
                accepted += 1
            else:
                skipped.append(f"#{tid}: {msg}")
        flash = f"Accepted {accepted} of {len(ids)} matched transaction(s)."
        if skipped:
            flash += f" {len(skipped)} skipped: " + "; ".join(skipped[:3])
            if len(skipped) > 3:
                flash += f"; (+{len(skipped) - 3} more)"
        return back, flash

    def handle_unignore(self, bank_txn_id: int) -> tuple[str, str]:
        """Reverse an IGNORED bank transaction back to UNVALIDATED so it
        re-enters the validation queue. Match metadata is cleared so the
        next Re-validate run will recompute it."""
        back = "/bank-transactions/pending?show_ignored=1"
        cur = self._conn.execute(
            """
            UPDATE bank_transactions
               SET validation_status = 'UNVALIDATED',
                   match_type         = 'UNMATCHED',
                   rule_id             = NULL,
                   matched_source_type = NULL,
                   matched_source_id   = NULL
             WHERE id = ? AND validation_status = 'IGNORED'
            """,
            (bank_txn_id,),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            return back, "Transaction not in ignored status — no action taken."
        return back, "Reset to pending — click ↻ Re-validate to refresh matches."

    def handle_ignore(self, bank_txn_id: int) -> tuple[str, str]:
        """Mark a bank transaction as IGNORED. No ledger record created."""
        back = "/bank-transactions/pending"
        cur = self._conn.execute(
            """
            UPDATE bank_transactions
               SET validation_status = 'IGNORED'
             WHERE id = ? AND validation_status = 'UNVALIDATED'
            """,
            (bank_txn_id,),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            return back, "Transaction not pending — no action taken."
        return back, "Marked as ignored."

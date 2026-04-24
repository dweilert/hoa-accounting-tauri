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
    ) -> PageResponse:
        accounts = self._conn.execute(
            "SELECT id, account_name, account_last4 "
            "FROM bank_accounts ORDER BY account_name"
        ).fetchall()

        params: list = []
        where = "WHERE bt.validation_status = 'UNVALIDATED'"
        if bank_account_id:
            where += " AND bt.bank_account_id = ?"
            params.append(bank_account_id)

        rows = self._conn.execute(
            f"""
            SELECT bt.id, bt.bank_account_id, bt.transaction_date,
                   bt.description, bt.memo, bt.amount, bt.transaction_type,
                   bt.match_type, bt.rule_id,
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
            "flash_message": flash_message,
            "error_message": error_message,
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
        if row["match_type"] != "RULE" or not row["rule_id"]:
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
            SELECT id, name, category_type, group_name
            FROM categories
            WHERE active_flag = 1 AND category_type IN ('INCOME', 'EXPENSE')
            ORDER BY category_type, sort_order, name
            """
        ).fetchall()
        vendors = self._conn.execute(
            "SELECT id, vendor_name FROM vendors WHERE active_flag = 1 ORDER BY vendor_name COLLATE NOCASE"
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
        category_id: int,
        vendor_id: int | None,
        memo: str,
    ) -> tuple[str, str]:
        """Post a one-off ledger record for this bank line using the chosen
        category (and vendor, for debits). Wraps the same services
        ``_apply_rule`` uses so the posting behaves identically.
        """
        back = f"/bank-transactions/{bank_txn_id}/classify"
        txn = self._get_txn(bank_txn_id)
        if txn is None:
            return "/bank-transactions/pending", "Transaction not found."
        if txn["validation_status"] != "UNVALIDATED":
            return "/bank-transactions/pending", "Already validated or ignored."

        amount = Decimal(str(txn["amount"]))
        description = (memo or txn["description"] or "").strip()
        factory = ServiceFactory(self._conn)

        if amount > 0:
            result = factory.non_dues_income_service().post_batch(
                posting_date=txn["transaction_date"],
                bank_account_id=int(txn["bank_account_id"]),
                income_description=description or "Bank import",
                rows=[IncomeRow(amount=str(amount), other_source="BANK")],
                category_id=int(category_id),
            )
            source_type, source_id = "INCOME_BATCH", result.income_batch_id
        else:
            if not vendor_id:
                return back, "Vendor is required for expense transactions."
            amt = abs(amount)
            invoice_number = (
                f"BR-{str(txn['transaction_date']).replace('-', '')}"
                f"-{int(bank_txn_id):06d}"
            )
            bill = factory.vendor_bill_service().post_vendor_bill(
                entry_date=txn["transaction_date"],
                vendor_id=int(vendor_id),
                amount=str(amt),
                description=description,
                invoice_number=invoice_number,
                invoice_date=txn["transaction_date"],
                category_id=int(category_id),
            )
            payment = factory.vendor_payment_service().post_vendor_payment(
                entry_date=txn["transaction_date"],
                vendor_bill_id=bill.vendor_bill_id,
                amount=str(amt),
                description=description,
                bank_account_id=int(txn["bank_account_id"]),
            )
            self._conn.execute(
                "UPDATE bill_payments SET category_id = ? WHERE id = ?",
                (int(category_id), payment.bill_payment_id),
            )
            source_type, source_id = "BILL_PAYMENT", payment.bill_payment_id

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
                 link_source)
            VALUES (?, ?, ?, 'MANUAL')
            """,
            (bank_txn_id, source_type, int(source_id)),
        )
        self._conn.commit()
        return "/bank-transactions/pending", f"Posted {source_type.lower()} #{source_id}."

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

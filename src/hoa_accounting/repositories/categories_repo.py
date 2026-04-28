"""Repository for expense/income categories."""

from __future__ import annotations

import sqlite3

from .base import BaseRepository


class CategoriesRepository(BaseRepository):
    """Database access for the categories table."""

    def list_categories(
        self,
        *,
        category_type: str | None = None,
        active_only: bool = True,
    ) -> list[sqlite3.Row]:
        where = "WHERE 1=1"
        params: list[object] = []
        if active_only:
            where += " AND active_flag = 1"
        if category_type:
            where += " AND category_type = ?"
            params.append(category_type)
        return list(
            self.conn.execute(
                f"""
                SELECT id, code, name, category_type, fund_code, sort_order,
                       group_name, description, active_flag
                FROM categories
                {where}
                ORDER BY
                    CASE category_type
                        WHEN 'INCOME'   THEN 0
                        WHEN 'EXPENSE'  THEN 1
                        WHEN 'TRANSFER' THEN 2
                        ELSE 3
                    END,
                    code COLLATE NOCASE
                """,
                params,
            ).fetchall()
        )

    def get_category(self, category_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """SELECT id, code, name, category_type, fund_code, sort_order,
                      group_name, description, active_flag
               FROM categories WHERE id = ?""",
            (category_id,),
        ).fetchone()

    def update_category(
        self,
        category_id: int,
        *,
        name: str,
        group_name: str | None,
        description: str | None,
        fund_code: str,
        sort_order: int,
        active_flag: int,
    ) -> None:
        self.conn.execute(
            """UPDATE categories
               SET name = ?, group_name = ?, description = ?,
                   fund_code = ?, sort_order = ?, active_flag = ?
               WHERE id = ?""",
            (name, group_name, description, fund_code, sort_order, active_flag, category_id),
        )
        self.conn.commit()

    def insert_category(
        self,
        *,
        code: str,
        name: str,
        category_type: str,
        fund_code: str,
        sort_order: int,
        group_name: str | None,
        description: str | None,
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO categories
                   (code, name, category_type, fund_code, sort_order, group_name, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (code, name, category_type, fund_code, sort_order, group_name, description),
        )
        self.conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # Every table that carries a category_id column. If any of these have a
    # row referencing the category, deletion is blocked.
    _CATEGORY_REFERENCE_TABLES: tuple[str, ...] = (
        "assessments",
        "bank_transaction_rules",
        "bank_transactions",
        "budget_lines",
        "deposit_batches",
        "income_batches",
        "owner_adjustments",
        "payments",
        "reserve_transfers",
        "vendor_bills",
    )

    # Tables whose rows show up in the category ledger view. Splitting these
    # out keeps the "Transactions" count on the categories list aligned with
    # what the ledger actually displays.
    _LEDGER_TABLES: tuple[str, ...] = (
        "assessments",
        "income_batches",
        "reserve_transfers",
        "vendor_bills",
    )

    def usage_count(self, category_id: int) -> int:
        """Total references across every table — gates the delete action."""
        total = 0
        for table in self._CATEGORY_REFERENCE_TABLES:
            row = self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE category_id = ?",
                (category_id,),
            ).fetchone()
            total += int(row["n"])
        return total

    def usage_breakdown(self, category_id: int) -> dict[str, int]:
        """Return ``{"transactions": n, "other": n, "total": n}``.

        * ``transactions`` — rows that show up in the category ledger view
          (vendor bills, income batches, assessments, reserve transfers).
        * ``other`` — non-ledger references: budget lines, bank-transaction
          rules, raw bank rows, payments, owner adjustments, deposit batches.

        The split lets the UI distinguish "this category has actual spending"
        from "this category is referenced by a plan / rule / staging row".
        """
        counts: dict[str, int] = {"transactions": 0, "other": 0}
        for table in self._CATEGORY_REFERENCE_TABLES:
            row = self.conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE category_id = ?",
                (category_id,),
            ).fetchone()
            n = int(row["n"])
            bucket = "transactions" if table in self._LEDGER_TABLES else "other"
            counts[bucket] += n
        counts["total"] = counts["transactions"] + counts["other"]
        return counts

    def delete_category(self, category_id: int) -> None:
        """Hard-delete a category. Caller must check ``usage_count`` first."""
        self.conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        self.conn.commit()

    def ledger_for_category(self, category_id: int) -> list[sqlite3.Row]:
        """Return all transactions tagged with this category, newest first."""
        return list(
            self.conn.execute(
                """
                SELECT 'Bill' AS txn_type,
                       vb.invoice_date AS txn_date,
                       vb.invoice_number AS ref,
                       v.vendor_name AS party,
                       vb.amount,
                       vb.description AS memo,
                       vb.status,
                       NULL AS entry_number
                FROM vendor_bills vb
                LEFT JOIN vendors v ON v.id = vb.vendor_id
                WHERE vb.category_id = ?

                UNION ALL

                SELECT 'Income' AS txn_type,
                       ib.posting_date,
                       NULL AS ref,
                       ba.account_name AS party,
                       ib.total_amount AS amount,
                       ib.income_description AS memo,
                       NULL AS status,
                       NULL AS entry_number
                FROM income_batches ib
                LEFT JOIN bank_accounts ba ON ba.id = ib.bank_account_id
                WHERE ib.category_id = ?

                UNION ALL

                SELECT 'Assessment' AS txn_type,
                       a.assessment_date AS txn_date,
                       NULL AS ref,
                       (SELECT l.street_address_1 FROM lots l WHERE l.id = a.lot_id) AS party,
                       a.amount,
                       a.description AS memo,
                       a.status,
                       NULL AS entry_number
                FROM assessments a
                WHERE a.category_id = ?

                UNION ALL

                SELECT 'Transfer' AS txn_type,
                       rt.transfer_date AS txn_date,
                       NULL AS ref,
                       NULL AS party,
                       rt.amount,
                       rt.notes AS memo,
                       rt.transfer_type AS status,
                       NULL AS entry_number
                FROM reserve_transfers rt
                WHERE rt.category_id = ?

                ORDER BY txn_date DESC
                """,
                (category_id, category_id, category_id, category_id),
            ).fetchall()
        )

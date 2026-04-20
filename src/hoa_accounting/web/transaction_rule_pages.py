"""Page service for managing bank transaction rules."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


class TransactionRulePages:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def _render(self, template: str, **ctx) -> PageResponse:
        return PageResponse(200, render_template(template, ctx))

    def _get_accounts(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT a.id, a.account_number, a.account_name, at.code AS account_type
            FROM accounts a
            JOIN account_types at ON at.id = a.account_type_id
            WHERE at.code IN ('EXPENSE', 'INCOME')
              AND a.is_active = 1
            ORDER BY a.account_number
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_rules(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT r.id, r.rule_name, r.description_contains, r.action_type,
                   r.gl_account_id, r.default_memo, r.active_flag, r.created_at,
                   a.account_number, a.account_name
            FROM bank_transaction_rules r
            LEFT JOIN accounts a ON a.id = r.gl_account_id
            ORDER BY r.rule_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def render_list(self, org: dict, theme: str) -> PageResponse:
        rules = self._get_rules()
        accounts = self._get_accounts()
        return self._render(
            "transaction_rules.html",
            org=org, theme=theme,
            page_key="transaction-rules",
            rules=rules,
            accounts=accounts,
        )

    def handle_save(
        self,
        form_data: dict,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        rule_id = form_data.get("rule_id", "").strip()
        rule_name = form_data.get("rule_name", "").strip()
        desc_contains = form_data.get("description_contains", "").strip()
        action_type = form_data.get("action_type", "direct_expense").strip()
        gl_account_id = form_data.get("gl_account_id", "").strip() or None
        default_memo = form_data.get("default_memo", "").strip()
        active_flag = 1 if form_data.get("active_flag") else 0

        if not rule_name:
            rules = self._get_rules()
            accounts = self._get_accounts()
            return None, self._render(
                "transaction_rules.html",
                org=org, theme=theme,
                page_key="transaction-rules",
                rules=rules,
                accounts=accounts,
                error="Rule name is required.",
            )

        if action_type not in ("direct_expense", "direct_income"):
            action_type = "direct_expense"

        if rule_id:
            self._conn.execute(
                """
                UPDATE bank_transaction_rules
                SET rule_name = ?, description_contains = ?, action_type = ?,
                    gl_account_id = ?, default_memo = ?, active_flag = ?
                WHERE id = ?
                """,
                (rule_name, desc_contains, action_type,
                 gl_account_id, default_memo, active_flag, int(rule_id)),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO bank_transaction_rules
                    (rule_name, description_contains, action_type,
                     gl_account_id, default_memo, active_flag)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (rule_name, desc_contains, action_type,
                 gl_account_id, default_memo, active_flag),
            )

        self._conn.commit()
        return "/admin/transaction-rules", None

    def handle_delete(self, rule_id: int) -> str:
        self._conn.execute(
            "DELETE FROM bank_transaction_rules WHERE id = ?", (rule_id,)
        )
        self._conn.commit()
        return "/admin/transaction-rules"

    def handle_toggle(self, rule_id: int) -> str:
        self._conn.execute(
            "UPDATE bank_transaction_rules SET active_flag = 1 - active_flag WHERE id = ?",
            (rule_id,),
        )
        self._conn.commit()
        return "/admin/transaction-rules"

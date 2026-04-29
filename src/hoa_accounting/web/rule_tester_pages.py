"""Rule Tester page — try a transaction rule against a real or synthetic
bank row before posting it for real.

Two modes for picking the test transaction:
1. **Pick existing** — choose a row from ``bank_transactions`` by id.
2. **Synthetic** — fill in description / memo / amount / type / bank.

Output: per-criterion ✓/✗ for the selected rule, plus the list of any
*other* rules that would also fire on the same row (rule-order conflict
warning).
"""

from __future__ import annotations
from typing import Any

import sqlite3
from dataclasses import asdict, dataclass
from decimal import Decimal
from http import HTTPStatus

from hoa_accounting.services.rule_diagnoser import (
    MatchReport,
    diagnose,
    find_other_matches,
)
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class RuleTesterResponse:
    status_code: int
    body_html: str


class RuleTesterPages:
    TEMPLATE = "rule_tester.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── Helpers ───────────────────────────────────────────────────────

    def _all_rules(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, rule_name, description_contains, match_memo,
                   match_type, match_amount, match_amount AS amount,
                   bank_account_id, active_flag, action_type
              FROM bank_transaction_rules
             ORDER BY rule_name COLLATE NOCASE
            """
        ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def _recent_txns(self, limit: int = 25) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT bt.id, bt.transaction_date, bt.description, bt.memo,
                   bt.amount, bt.transaction_type, bt.bank_account_id,
                   ba.account_name, ba.account_last4
              FROM bank_transactions bt
              JOIN bank_accounts ba ON ba.id = bt.bank_account_id
             ORDER BY bt.transaction_date DESC, bt.id DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def _txn_by_id(self, txn_id: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT id, transaction_date, description, memo, amount,
                   transaction_type, bank_account_id
              FROM bank_transactions WHERE id = ?
            """,
            (txn_id,),
        ).fetchone()
        return {k: row[k] for k in row.keys()} if row else None

    # ── GET ───────────────────────────────────────────────────────────

    def render(
        self,
        *,
        org: dict[str, Any],
        theme: str,
        focus_rule_id: int | None = None,
        txn_id: int | None = None,
        synthetic: dict[str, Any] | None = None,
    ) -> RuleTesterResponse:
        rules = self._all_rules()

        # Resolve the test transaction.
        txn: dict[str, Any] | None = None
        if txn_id:
            txn = self._txn_by_id(txn_id)
        elif synthetic and any(synthetic.values()):
            txn = {
                "description": str(synthetic.get("description") or "").strip(),
                "memo":        str(synthetic.get("memo") or "").strip(),
                "amount":      str(synthetic.get("amount") or "0").strip() or "0",
                "transaction_type": str(synthetic.get("transaction_type") or "").strip().upper(),
                "bank_account_id": int(synthetic["bank_account_id"])
                                   if synthetic.get("bank_account_id") else None,
            }

        # Resolve the focus rule.
        focus_report: MatchReport | None = None
        other_matches: list[MatchReport] = []
        if focus_rule_id and txn:
            focus = next((r for r in rules if r["id"] == focus_rule_id), None)
            if focus:
                focus_report = diagnose(focus, txn)
                other_matches = find_other_matches(
                    rules, txn, exclude_rule_id=focus_rule_id,
                )
        elif txn and not focus_rule_id:
            # No focus rule chosen: just show every rule that matches.
            other_matches = find_other_matches(rules, txn)

        ctx = {
            "heading": "Rule Tester",
            "breadcrumb": "Bank · Transaction Rules",
            "parent_url": "/admin/transaction-rules",
            "org": org or {},
            "theme": theme,
            "active_nav": "transactions",
            "page_key": "transaction-rules",
            "rules": rules,
            "recent_txns": self._recent_txns(),
            "selected_rule_id": focus_rule_id,
            "selected_txn_id": txn_id,
            "synthetic": synthetic or {},
            "txn": txn,
            "focus_report": _serialize(focus_report) if focus_report else None,
            "other_matches": [_serialize(m) for m in other_matches],
        }
        return RuleTesterResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.TEMPLATE, ctx),
        )


def _serialize(report: MatchReport) -> dict[str, Any]:
    return {
        "rule_id": report.rule_id,
        "rule_name": report.rule_name,
        "would_match": report.would_match,
        "checks": [asdict(c) for c in report.checks],
    }

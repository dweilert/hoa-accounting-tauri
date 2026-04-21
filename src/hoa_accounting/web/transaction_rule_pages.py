"""Page service for managing bank transaction rules."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from hoa_accounting.web.template_engine import render_template

# Maps action_type → (label, accounting_pattern, preferred_account_type)
# pattern "expense" = DR gl_account / CR bank
# pattern "income"  = DR bank       / CR gl_account
ACTION_TYPES: dict[str, dict] = {
    "recurring_bill": {
        "label":        "Recurring Bill / Auto-Pay",
        "description":  "Utilities, insurance, landscaping, management fees",
        "pattern":      "expense",
        "acct_type":    "EXPENSE",
    },
    "dues_payment": {
        "label":        "Dues or Assessment Payment",
        "description":  "Monthly dues deposits or special assessments received",
        "pattern":      "income",
        "acct_type":    "INCOME",
    },
    "fee_income": {
        "label":        "Fee or Other Income",
        "description":  "Late fees, resale fees, interest earned, refunds",
        "pattern":      "income",
        "acct_type":    "INCOME",
    },
    "bank_charge": {
        "label":        "Bank Fee or Charge",
        "description":  "Monthly service fees, wire fees, NSF charges",
        "pattern":      "expense",
        "acct_type":    "EXPENSE",
    },
    # Legacy values kept for backward compatibility
    "direct_expense": {
        "label":        "Direct Expense (legacy)",
        "description":  "",
        "pattern":      "expense",
        "acct_type":    "EXPENSE",
    },
    "direct_income": {
        "label":        "Direct Income (legacy)",
        "description":  "",
        "pattern":      "income",
        "acct_type":    "INCOME",
    },
}

VALID_ACTION_TYPES = set(ACTION_TYPES.keys())


def action_pattern(action_type: str) -> str:
    """Return 'expense' or 'income' for the given action_type."""
    return ACTION_TYPES.get(action_type, ACTION_TYPES["recurring_bill"])["pattern"]


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
        """Return all active accounts with their type code."""
        rows = self._conn.execute(
            """
            SELECT a.id, a.account_number, a.account_name, at.code AS account_type
            FROM accounts a
            JOIN account_types at ON at.id = a.account_type_id
            WHERE a.is_active = 1
            ORDER BY a.account_number
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_bank_accounts(self) -> list[dict]:
        """Return all bank accounts for the rule restriction dropdown."""
        rows = self._conn.execute(
            """
            SELECT id, account_name, account_last4, institution_name
            FROM bank_accounts
            ORDER BY account_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_lots(self) -> list[dict]:
        """Return all active lots with their current owner name(s)."""
        rows = self._conn.execute(
            """
            SELECT l.id, l.lot_number,
                   COALESCE(GROUP_CONCAT(o.display_name, ', '), '') AS owner_name
            FROM lots l
            LEFT JOIN lot_ownership lo ON lo.lot_id = l.id AND lo.end_date IS NULL
            LEFT JOIN owners o ON o.id = lo.owner_id
            WHERE l.active_flag = 1
            GROUP BY l.id
            ORDER BY l.lot_number
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_rules(self) -> list[dict]:
        rows = self._conn.execute(
            """
            SELECT r.id, r.rule_name, r.description_contains,
                   r.match_type, r.match_memo, r.match_amount, r.bank_account_id,
                   r.action_type, r.gl_account_id, r.default_memo, r.active_flag, r.created_at,
                   r.lot_id,
                   a.account_number, a.account_name,
                   l.lot_number,
                   o.display_name AS lot_owner_name,
                   ba.account_name AS bank_account_name,
                   ba.account_last4
            FROM bank_transaction_rules r
            LEFT JOIN accounts a ON a.id = r.gl_account_id
            LEFT JOIN lots l ON l.id = r.lot_id
            LEFT JOIN (
                SELECT lot_id, owner_id FROM lot_ownership
                WHERE end_date IS NULL
                GROUP BY lot_id
            ) lo ON lo.lot_id = r.lot_id
            LEFT JOIN owners o ON o.id = lo.owner_id
            LEFT JOIN bank_accounts ba ON ba.id = r.bank_account_id
            ORDER BY r.rule_name
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def _get_gl_suggestions(self, bank_accounts: list[dict]) -> dict:
        """Return {str(bank_account_id|"any"): {"income": [acct_id,...], "expense": [...]}}
        built from journal entry history for smarter GL pre-selection."""
        suggestions: dict[str, dict[str, list[int]]] = {}

        def _query(gl_account_id: int | None) -> dict[str, list[int]]:
            base = """
                SELECT jel_other.account_id, at.code AS acct_type, COUNT(*) AS cnt
                FROM journal_entry_lines jel_bank
                JOIN journal_entries je ON je.id = jel_bank.journal_entry_id
                JOIN journal_entry_lines jel_other
                    ON jel_other.journal_entry_id = je.id
                   AND jel_other.id != jel_bank.id
                JOIN accounts a ON a.id = jel_other.account_id
                JOIN account_types at ON at.id = a.account_type_id
                WHERE {where}
                  AND je.status = 'POSTED'
                  AND at.code IN ('INCOME', 'EXPENSE')
                GROUP BY jel_other.account_id
                ORDER BY cnt DESC
                LIMIT 10
            """
            result: dict[str, list[int]] = {"income": [], "expense": []}
            if gl_account_id:
                # income = money coming INTO bank (debit on bank line)
                rows = self._conn.execute(
                    base.format(where="jel_bank.account_id = ? AND jel_bank.debit_amount > 0"),
                    (gl_account_id,),
                ).fetchall()
                for r in rows:
                    if r["acct_type"] == "INCOME":
                        result["income"].append(r["account_id"])
                # expense = money going OUT of bank (credit on bank line)
                rows = self._conn.execute(
                    base.format(where="jel_bank.account_id = ? AND jel_bank.credit_amount > 0"),
                    (gl_account_id,),
                ).fetchall()
                for r in rows:
                    if r["acct_type"] == "EXPENSE":
                        result["expense"].append(r["account_id"])
            else:
                rows = self._conn.execute(
                    base.format(where="at.code = 'INCOME' AND jel_bank.debit_amount > 0"),
                ).fetchall()
                result["income"] = [r["account_id"] for r in rows]
                rows = self._conn.execute(
                    base.format(where="at.code = 'EXPENSE' AND jel_bank.credit_amount > 0"),
                ).fetchall()
                result["expense"] = [r["account_id"] for r in rows]
            return result

        suggestions["any"] = _query(None)
        for ba in bank_accounts:
            gl_id = self._conn.execute(
                "SELECT gl_account_id FROM bank_accounts WHERE id = ?", (ba["id"],)
            ).fetchone()
            if gl_id and gl_id["gl_account_id"]:
                suggestions[str(ba["id"])] = _query(int(gl_id["gl_account_id"]))
            else:
                suggestions[str(ba["id"])] = {"income": [], "expense": []}

        return suggestions

    def render_list(self, org: dict, theme: str, return_to: str = "") -> PageResponse:
        rules = self._get_rules()
        accounts = self._get_accounts()
        lots = self._get_lots()
        bank_accounts = self._get_bank_accounts()
        gl_suggestions = self._get_gl_suggestions(bank_accounts)
        return self._render(
            "transaction_rules.html",
            org=org, theme=theme,
            page_key="transaction-rules",
            rules=rules,
            accounts=accounts,
            lots=lots,
            bank_accounts=bank_accounts,
            gl_suggestions=gl_suggestions,
            action_types=ACTION_TYPES,
            return_to=return_to,
        )

    def handle_save(
        self,
        form_data: dict,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        rule_id        = form_data.get("rule_id", "").strip()
        rule_name      = form_data.get("rule_name", "").strip()
        desc_contains  = form_data.get("description_contains", "").strip()
        match_type        = form_data.get("match_type", "").strip()
        match_memo        = form_data.get("match_memo", "").strip()
        match_amount      = form_data.get("match_amount", "").strip().lstrip("$").replace(",", "")
        ba_id_raw         = form_data.get("bank_account_id", "").strip()
        rule_bank_acct_id = int(ba_id_raw) if ba_id_raw else None
        action_type    = form_data.get("action_type", "recurring_bill").strip()
        gl_account_id  = form_data.get("gl_account_id", "").strip() or None
        lot_id_raw     = form_data.get("lot_id", "").strip()
        lot_id         = int(lot_id_raw) if lot_id_raw else None
        default_memo   = form_data.get("default_memo", "").strip()
        active_flag    = 1 if form_data.get("active_flag") else 0

        # lot_id only applies to dues_payment rules
        if action_type != "dues_payment":
            lot_id = None

        if not rule_name:
            return None, self._render_error("Rule name is required.", org, theme)

        if action_type not in VALID_ACTION_TYPES:
            action_type = "recurring_bill"

        # Block duplicate names (skip the current rule when editing)
        existing = self._conn.execute(
            "SELECT id FROM bank_transaction_rules WHERE rule_name = ? AND id != ?",
            (rule_name, int(rule_id) if rule_id else -1),
        ).fetchone()
        if existing:
            return None, self._render_error(
                f'A rule named "{rule_name}" already exists. Please use a different name.',
                org, theme,
            )

        if rule_id:
            self._conn.execute(
                """
                UPDATE bank_transaction_rules
                SET rule_name = ?, description_contains = ?,
                    match_type = ?, match_memo = ?, match_amount = ?, bank_account_id = ?,
                    action_type = ?, gl_account_id = ?, lot_id = ?,
                    default_memo = ?, active_flag = ?
                WHERE id = ?
                """,
                (rule_name, desc_contains, match_type, match_memo, match_amount,
                 rule_bank_acct_id, action_type, gl_account_id, lot_id,
                 default_memo, active_flag, int(rule_id)),
            )
        else:
            self._conn.execute(
                """
                INSERT INTO bank_transaction_rules
                    (rule_name, description_contains, match_type, match_memo, match_amount,
                     bank_account_id, action_type, gl_account_id, lot_id, default_memo, active_flag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rule_name, desc_contains, match_type, match_memo, match_amount,
                 rule_bank_acct_id, action_type, gl_account_id, lot_id,
                 default_memo, active_flag),
            )

        self._conn.commit()
        return "/admin/transaction-rules", None

    def _render_error(self, error: str, org: dict, theme: str) -> PageResponse:
        bank_accounts = self._get_bank_accounts()
        return self._render(
            "transaction_rules.html",
            org=org, theme=theme,
            page_key="transaction-rules",
            rules=self._get_rules(),
            accounts=self._get_accounts(),
            lots=self._get_lots(),
            bank_accounts=bank_accounts,
            gl_suggestions=self._get_gl_suggestions(bank_accounts),
            action_types=ACTION_TYPES,
            error=error,
        )

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

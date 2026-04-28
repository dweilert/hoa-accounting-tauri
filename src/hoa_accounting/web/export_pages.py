"""
Master-data export page — System › Export Data.

Lets the user select one or more data sets, then downloads them as a
ZIP archive.  Each data set becomes its own file inside the ZIP:

  • Always comma-separated (.csv).
  • Any comma that appears inside a cell value is replaced with the
    HTML entity &#x2C; so it is never confused with a field delimiter.
    On import, &#x2C; must be converted back to a literal comma.

The ZIP is built entirely in memory and streamed to the browser; nothing
is written to disk.
"""

from __future__ import annotations

import io
import sqlite3
import zipfile
from dataclasses import dataclass
from http import HTTPStatus

from hoa_accounting.web.template_engine import render_template


# ── Exportable data sets ─────────────────────────────────────────────────────

EXPORT_GROUPS: list[dict] = [
    {
        "title": "Master Data",
        "types": [
            {"key": "hoa_profile",      "label": "HOA Profile",            "filename": "hoa_profile"},
            {"key": "board_members",    "label": "Board Members",          "filename": "board_members"},
            {"key": "accounts",         "label": "Chart of Accounts",      "filename": "accounts"},
            {"key": "account_types",    "label": "Account Types (lookup)", "filename": "account_types"},
            {"key": "owners",           "label": "Owners",                 "filename": "owners"},
            {"key": "lots",             "label": "Lots",                   "filename": "lots"},
            {"key": "lot_ownership",    "label": "Lot Ownership History",  "filename": "lot_ownership"},
            {"key": "renters",          "label": "Renters",                "filename": "renters"},
            {"key": "vendors",          "label": "Vendors",                "filename": "vendors"},
            {"key": "bank_accounts",    "label": "Bank Accounts",          "filename": "bank_accounts"},
            {"key": "budgets",          "label": "Budgets",                "filename": "budgets"},
            {"key": "budget_lines",     "label": "Budget Line Detail",     "filename": "budget_lines"},
            {"key": "assessment_rules", "label": "Assessment Rules",       "filename": "assessment_rules"},
            {"key": "bill_templates",   "label": "Recurring Bill Templates","filename": "bill_templates"},
        ],
    },
    {
        "title": "Transactions & Financials",
        "types": [
            {"key": "assessments",           "label": "Assessments / Charges",                "filename": "assessments"},
            {"key": "payments",              "label": "Payments Received",                     "filename": "payments"},
            {"key": "payment_applications",  "label": "Payment Applications (charge detail)",  "filename": "payment_applications"},
            {"key": "owner_adjustments",     "label": "Owner Adjustments (credits/write-offs)","filename": "owner_adjustments"},
            {"key": "dues_billing_history",  "label": "Dues Billing History",                  "filename": "dues_billing_history"},
            {"key": "vendor_bills",          "label": "Vendor Bills",                          "filename": "vendor_bills"},
            {"key": "bill_payments",         "label": "Bill Payments",                         "filename": "bill_payments"},
            {"key": "deposit_batches",       "label": "Deposit Batches",                       "filename": "deposit_batches"},
            {"key": "non_dues_income",       "label": "Non-Dues Income",                       "filename": "non_dues_income"},
            {"key": "journal_entries",       "label": "Journal Entries (header)",              "filename": "journal_entries"},
            {"key": "journal_entry_lines",   "label": "Journal Entry Lines",                   "filename": "journal_entry_lines"},
            {"key": "bank_transactions",     "label": "Bank Transactions (canonical feed)",    "filename": "bank_transactions"},
            {"key": "bank_transaction_rules","label": "Bank Transaction Rules",                "filename": "bank_transaction_rules"},
        ],
    },
    {
        "title": "Historical & Operational",
        "types": [
            {"key": "bank_reconciliations",  "label": "Bank Reconciliations",   "filename": "bank_reconciliations"},
            {"key": "reserve_transfers",     "label": "Reserve Transfers",       "filename": "reserve_transfers"},
            {"key": "opening_balances",      "label": "Opening Balances",        "filename": "opening_balances"},
            {"key": "accounting_periods",    "label": "Accounting Periods",      "filename": "accounting_periods"},
            {"key": "fiscal_year_closes",    "label": "Fiscal Year Closes",      "filename": "fiscal_year_closes"},
        ],
    },
    {
        "title": "Reserve Study",
        "types": [
            {"key": "reserve_assets",            "label": "Reserve Assets",             "filename": "reserve_assets"},
            {"key": "reserve_components",        "label": "Reserve Components",         "filename": "reserve_components"},
            {"key": "reserve_study_assumptions", "label": "Reserve Study Assumptions",  "filename": "reserve_study_assumptions"},
            {"key": "reserve_study_scenarios",   "label": "Reserve Study Scenarios",    "filename": "reserve_study_scenarios"},
        ],
    },
]

# Flat list kept for backwards-compatible iteration in build_zip.
EXPORT_TYPES: list[dict] = [t for g in EXPORT_GROUPS for t in g["types"]]

# Map each key → SQL that produces a flat, human-readable result set.
QUERIES: dict[str, str] = {
    "accounts": """
        SELECT
            a.account_number,
            a.account_name,
            at.name         AS account_type,
            at.normal_balance,
            a.fund_code,
            CASE a.is_bank_account WHEN 1 THEN 'Yes' ELSE 'No' END AS is_bank_account,
            CASE a.is_active       WHEN 1 THEN 'Yes' ELSE 'No' END AS active,
            a.description
        FROM accounts a
        JOIN account_types at ON at.id = a.account_type_id
        ORDER BY a.account_number
    """,
    "owners": """
        SELECT
            owner_type, display_name, first_name, last_name, entity_name,
            mailing_address_1, mailing_address_2, city, state, postal_code,
            phone, email,
            CASE active_flag WHEN 1 THEN 'Yes' ELSE 'No' END AS active,
            notes
        FROM owners
        ORDER BY display_name
    """,
    "lots": """
        SELECT
            l.lot_number,
            l.street_address_1, l.street_address_2,
            l.city, l.state, l.postal_code,
            l.legal_description,
            CASE l.active_flag WHEN 1 THEN 'Yes' ELSE 'No' END AS active,
            GROUP_CONCAT(o.display_name, '; ') AS current_owner
        FROM lots l
        LEFT JOIN lot_ownership lo
               ON lo.lot_id = l.id AND lo.end_date IS NULL
        LEFT JOIN owners o ON o.id = lo.owner_id
        GROUP BY l.id
        ORDER BY l.lot_number
    """,
    "lot_ownership": """
        SELECT
            l.lot_number,
            o.display_name  AS owner_name,
            lo.start_date,
            lo.end_date
        FROM lot_ownership lo
        JOIN lots   l ON l.id = lo.lot_id
        JOIN owners o ON o.id = lo.owner_id
        ORDER BY l.lot_number, lo.start_date
    """,
    "renters": """
        SELECT
            l.lot_number,
            r.display_name, r.first_name, r.last_name,
            r.email, r.phone,
            r.start_date, r.end_date,
            r.notes
        FROM lot_renters r
        JOIN lots l ON l.id = r.lot_id
        ORDER BY l.lot_number, r.start_date
    """,
    "vendors": """
        SELECT
            vendor_name, contact_name, email, phone,
            address_1, address_2, city, state, postal_code,
            CASE active_flag WHEN 1 THEN 'Yes' ELSE 'No' END AS active,
            notes
        FROM vendors
        ORDER BY vendor_name
    """,
    "bank_accounts": """
        SELECT
            ba.account_name,
            ba.institution_name,
            ba.account_last4,
            ba.account_type,
            a.account_number AS gl_account_number,
            a.account_name   AS gl_account_name,
            CASE ba.active_flag WHEN 1 THEN 'Yes' ELSE 'No' END AS active
        FROM bank_accounts ba
        JOIN accounts a ON a.id = ba.gl_account_id
        ORDER BY ba.account_name
    """,
    "budgets": """
        SELECT
            fiscal_year, fund_code, status, notes
        FROM budgets
        ORDER BY fiscal_year, fund_code
    """,
    "budget_lines": """
        SELECT
            b.fiscal_year,
            b.fund_code,
            a.account_number,
            a.account_name,
            bl.fiscal_period,
            bl.budget_amount
        FROM budget_lines bl
        JOIN budgets  b ON b.id = bl.budget_id
        JOIN accounts a ON a.id = bl.account_id
        ORDER BY b.fiscal_year, b.fund_code, a.account_number, bl.fiscal_period
    """,

    # ── Transactions & Financials ─────────────────────────────────────────

    "assessments": """
        SELECT
            l.lot_number,
            o.display_name        AS owner_name,
            a.charge_type,
            a.assessment_date,
            a.due_date,
            a.amount,
            a.status,
            a.description,
            je.entry_number       AS journal_entry
        FROM assessments a
        JOIN lots            l  ON l.id  = a.lot_id
        JOIN owners          o  ON o.id  = a.owner_id
        LEFT JOIN journal_entries je ON je.id = a.journal_entry_id
        ORDER BY a.assessment_date, l.lot_number
    """,

    "payments": """
        SELECT
            p.payment_date,
            o.display_name        AS owner_name,
            p.amount,
            p.payment_method,
            p.reference_number,
            ba.account_name       AS bank_account,
            ba.institution_name,
            je.entry_number       AS journal_entry,
            p.notes
        FROM payments p
        JOIN owners             o  ON o.id  = p.owner_id
        LEFT JOIN bank_accounts ba ON ba.id = p.bank_account_id
        LEFT JOIN journal_entries je ON je.id = p.journal_entry_id
        ORDER BY p.payment_date, o.display_name
    """,

    "payment_applications": """
        SELECT
            p.payment_date,
            o.display_name        AS owner_name,
            p.amount              AS payment_amount,
            p.payment_method,
            p.reference_number,
            l.lot_number,
            a.charge_type,
            a.assessment_date,
            a.due_date,
            a.amount              AS charge_amount,
            pa.applied_amount
        FROM payment_applications pa
        JOIN payments    p  ON p.id  = pa.payment_id
        JOIN assessments a  ON a.id  = pa.assessment_id
        JOIN owners      o  ON o.id  = p.owner_id
        JOIN lots        l  ON l.id  = a.lot_id
        ORDER BY p.payment_date, o.display_name, a.charge_type
    """,

    "vendor_bills": """
        SELECT
            v.vendor_name,
            vb.invoice_number,
            vb.invoice_date,
            vb.due_date,
            vb.amount,
            ea.account_number     AS expense_account_number,
            ea.account_name       AS expense_account_name,
            vb.fund_code,
            vb.status,
            vb.description,
            je.entry_number       AS journal_entry
        FROM vendor_bills vb
        JOIN vendors      v  ON v.id  = vb.vendor_id
        JOIN accounts     ea ON ea.id = vb.expense_account_id
        LEFT JOIN journal_entries je ON je.id = vb.journal_entry_id
        ORDER BY vb.invoice_date, v.vendor_name
    """,

    "deposit_batches": """
        SELECT
            db.deposit_date,
            ba.account_name       AS bank_account,
            ba.institution_name,
            db.total_amount,
            COUNT(p.id)           AS payment_count,
            je.entry_number       AS journal_entry,
            db.notes
        FROM deposit_batches db
        JOIN bank_accounts   ba ON ba.id = db.bank_account_id
        LEFT JOIN journal_entries je ON je.id = db.journal_entry_id
        LEFT JOIN payments   p  ON p.deposit_batch_id = db.id
        GROUP BY db.id, db.deposit_date, ba.account_name, ba.institution_name,
                 db.total_amount, je.entry_number, db.notes
        ORDER BY db.deposit_date
    """,

    "non_dues_income": """
        SELECT
            ib.posting_date,
            ba.account_name       AS bank_account,
            ia.account_number     AS income_account_number,
            ia.account_name       AS income_account_name,
            ib.income_description,
            ib.total_amount,
            je.entry_number       AS journal_entry,
            ib.notes
        FROM income_batches ib
        JOIN bank_accounts    ba ON ba.id = ib.bank_account_id
        JOIN accounts         ia ON ia.id = ib.income_account_id
        LEFT JOIN journal_entries je ON je.id = ib.journal_entry_id
        ORDER BY ib.posting_date
    """,

    # ── Historical & Operational ──────────────────────────────────────────

    "bank_reconciliations": """
        SELECT
            ba.account_name             AS bank_account,
            ba.institution_name,
            br.statement_ending_date,
            br.statement_beginning_balance,
            br.statement_ending_balance,
            br.book_balance,
            br.status,
            br.reconciled_at
        FROM bank_reconciliations br
        JOIN bank_accounts ba ON ba.id = br.bank_account_id
        ORDER BY br.statement_ending_date, ba.account_name
    """,

    "reserve_transfers": """
        SELECT
            rt.transfer_date,
            rt.transfer_type,
            rt.purpose,
            fa.account_number           AS from_account_number,
            fa.account_name             AS from_account_name,
            ta.account_number           AS to_account_number,
            ta.account_name             AS to_account_name,
            rt.amount,
            je.entry_number             AS journal_entry,
            rt.notes
        FROM reserve_transfers rt
        JOIN accounts fa ON fa.id = rt.from_account_id
        JOIN accounts ta ON ta.id = rt.to_account_id
        LEFT JOIN journal_entries je ON je.id = rt.journal_entry_id
        ORDER BY rt.transfer_date
    """,

    "opening_balances": """
        SELECT
            ob.as_of_date,
            ob.entity_type,
            CASE ob.entity_type
                WHEN 'account' THEN a.account_number
                WHEN 'lot'     THEN CAST(l.lot_number AS TEXT)
                ELSE CAST(ob.entity_id AS TEXT)
            END                         AS entity_key,
            CASE ob.entity_type
                WHEN 'account' THEN a.account_name
                WHEN 'lot'     THEN l.street_address_1
                ELSE ''
            END                         AS entity_name,
            ob.amount,
            je.entry_number             AS journal_entry
        FROM opening_balances ob
        LEFT JOIN accounts a ON a.id = ob.entity_id AND ob.entity_type = 'account'
        LEFT JOIN lots     l ON l.id = ob.entity_id AND ob.entity_type = 'lot'
        LEFT JOIN journal_entries je ON je.id = ob.journal_entry_id
        ORDER BY ob.as_of_date, ob.entity_type
    """,

    # ── Master Data additions ─────────────────────────────────────────────

    "hoa_profile": """
        SELECT
            legal_name, display_name, corporate_state,
            federal_tax_id, state_tax_id, formation_date,
            mailing_address_1, mailing_address_2, city, state, postal_code,
            phone, email, website,
            fiscal_year_start_month, timezone, default_currency,
            default_annual_dues, default_assessment_amount, default_billing_frequency,
            report_header_text, report_footer_text, theme
        FROM hoa_profile
        WHERE id = 1
    """,

    "board_members": """
        SELECT
            full_name, title, email, phone,
            start_date, end_date,
            CASE is_active WHEN 1 THEN 'Yes' ELSE 'No' END AS active,
            notes
        FROM board_members
        ORDER BY is_active DESC, title, full_name
    """,

    "account_types": """
        SELECT code, name, normal_balance, financial_statement_group
        FROM account_types
        ORDER BY code
    """,

    "assessment_rules": """
        SELECT
            ar.rule_name,
            ar.frequency,
            ar.default_amount,
            ar.fund_code,
            ia.account_number AS income_account_number,
            ia.account_name   AS income_account_name,
            ra.account_number AS receivable_account_number,
            ra.account_name   AS receivable_account_name,
            ar.effective_start_date,
            ar.effective_end_date,
            CASE ar.active_flag WHEN 1 THEN 'Yes' ELSE 'No' END AS active,
            ar.notes
        FROM assessment_rules ar
        JOIN accounts ia ON ia.id = ar.income_account_id
        JOIN accounts ra ON ra.id = ar.receivable_account_id
        ORDER BY ar.rule_name
    """,

    "bill_templates": """
        SELECT
            bt.template_name,
            v.vendor_name,
            ea.account_number AS expense_account_number,
            ea.account_name   AS expense_account_name,
            pa.account_number AS payable_account_number,
            pa.account_name   AS payable_account_name,
            bt.fund_code,
            bt.expense_classification,
            bt.default_amount,
            bt.description,
            CASE bt.active_flag WHEN 1 THEN 'Yes' ELSE 'No' END AS active
        FROM bill_templates bt
        JOIN vendors  v  ON v.id  = bt.vendor_id
        JOIN accounts ea ON ea.id = bt.expense_account_id
        JOIN accounts pa ON pa.id = bt.payable_account_id
        ORDER BY bt.template_name
    """,

    # ── Transactions & Financials additions ───────────────────────────────

    "owner_adjustments": """
        SELECT
            oa.adjustment_date,
            o.display_name AS owner_name,
            l.lot_number,
            oa.adjustment_type,
            oa.amount,
            oa.description,
            je.entry_number AS journal_entry
        FROM owner_adjustments oa
        JOIN owners o ON o.id = oa.owner_id
        JOIN lots   l ON l.id = oa.lot_id
        LEFT JOIN journal_entries je ON je.id = oa.journal_entry_id
        ORDER BY oa.adjustment_date, o.display_name
    """,

    "dues_billing_history": """
        SELECT
            cycle_type,
            period_label,
            period_year,
            period_sequence,
            amount,
            owner_count,
            billed_at
        FROM dues_billing_history
        ORDER BY period_year, period_sequence
    """,

    "bill_payments": """
        SELECT
            bp.payment_date,
            v.vendor_name,
            vb.invoice_number,
            bp.amount,
            ba.account_name AS bank_account,
            bp.check_number,
            je.entry_number AS journal_entry,
            bp.notes
        FROM bill_payments bp
        JOIN vendor_bills  vb ON vb.id = bp.vendor_bill_id
        JOIN vendors       v  ON v.id  = vb.vendor_id
        JOIN bank_accounts ba ON ba.id = bp.bank_account_id
        LEFT JOIN journal_entries je ON je.id = bp.journal_entry_id
        ORDER BY bp.payment_date, v.vendor_name
    """,

    "journal_entries": """
        SELECT
            je.entry_number,
            je.entry_date,
            ap.period_name AS accounting_period,
            je.source_type,
            je.source_id,
            je.status,
            rev.entry_number AS reversal_of,
            je.posted_at,
            je.memo
        FROM journal_entries je
        JOIN accounting_periods ap ON ap.id = je.accounting_period_id
        LEFT JOIN journal_entries rev ON rev.id = je.reversal_entry_id
        ORDER BY je.entry_date, je.entry_number
    """,

    "journal_entry_lines": """
        SELECT
            je.entry_number,
            jel.line_number,
            a.account_number,
            a.account_name,
            l.lot_number,
            o.display_name AS owner_name,
            v.vendor_name,
            jel.debit_amount,
            jel.credit_amount,
            jel.expense_classification,
            jel.description
        FROM journal_entry_lines jel
        JOIN journal_entries je ON je.id = jel.journal_entry_id
        JOIN accounts        a  ON a.id  = jel.account_id
        LEFT JOIN lots    l ON l.id = jel.lot_id
        LEFT JOIN owners  o ON o.id = jel.owner_id
        LEFT JOIN vendors v ON v.id = jel.vendor_id
        ORDER BY je.entry_date, je.entry_number, jel.line_number
    """,

    "bank_transactions": """
        SELECT
            bt.transaction_date,
            ba.account_name AS bank_account,
            bt.description,
            bt.memo,
            bt.transaction_type,
            bt.amount,
            bt.external_reference,
            bt.reconciliation_status,
            bt.match_type,
            bt.validation_status,
            r.rule_name AS matched_rule,
            je.entry_number AS journal_entry
        FROM bank_transactions bt
        JOIN bank_accounts ba ON ba.id = bt.bank_account_id
        LEFT JOIN bank_transaction_rules r ON r.id = bt.rule_id
        LEFT JOIN journal_entries je ON je.id = bt.matched_journal_entry_id
        ORDER BY bt.transaction_date, ba.account_name
    """,

    "bank_transaction_rules": """
        SELECT
            r.rule_name,
            r.action_type,
            r.description_contains,
            r.match_type,
            r.match_memo,
            r.match_amount,
            ba.account_name AS bank_account,
            a.account_number AS gl_account_number,
            a.account_name   AS gl_account_name,
            v.vendor_name,
            l.lot_number,
            r.default_memo,
            r.confidence_mode,
            r.auto_post_after_n,
            r.confirmed_matches,
            CASE r.active_flag WHEN 1 THEN 'Yes' ELSE 'No' END AS active
        FROM bank_transaction_rules r
        LEFT JOIN bank_accounts ba ON ba.id = r.bank_account_id
        LEFT JOIN accounts      a  ON a.id  = r.gl_account_id
        LEFT JOIN vendors       v  ON v.id  = r.vendor_id
        LEFT JOIN lots          l  ON l.id  = r.lot_id
        ORDER BY r.rule_name
    """,

    # ── Historical & Operational additions ────────────────────────────────

    "accounting_periods": """
        SELECT
            period_name,
            fiscal_year,
            fiscal_period,
            start_date,
            end_date,
            CASE is_closed WHEN 1 THEN 'Yes' ELSE 'No' END AS closed,
            closed_at
        FROM accounting_periods
        ORDER BY fiscal_year, fiscal_period
    """,

    # ── Reserve Study ─────────────────────────────────────────────────────

    "reserve_assets": """
        SELECT
            asset_group, component, install_year, useful_life_years,
            condition, replacement_cost, annual_inflation,
            CASE active_flag WHEN 1 THEN 'Yes' ELSE 'No' END AS active,
            sort_order, notes
        FROM reserve_assets
        ORDER BY sort_order, asset_group, component
    """,

    "reserve_components": """
        SELECT
            component_name, useful_life_years, remaining_life_years,
            current_replacement_cost, funding_method,
            CASE active_flag WHEN 1 THEN 'Yes' ELSE 'No' END AS active,
            notes
        FROM reserve_components
        ORDER BY component_name
    """,

    "reserve_study_assumptions": """
        SELECT
            study_year,
            reserve_balance_override,
            annual_contribution,
            contribution_growth_rate,
            investment_return_rate,
            num_lots,
            projection_years,
            CASE is_active WHEN 1 THEN 'Yes' ELSE 'No' END AS active,
            notes
        FROM reserve_study_assumptions
        ORDER BY study_year
    """,

    "reserve_study_scenarios": """
        SELECT
            scenario_name, description,
            emergency_cost, expected_year,
            sort_order,
            CASE active_flag WHEN 1 THEN 'Yes' ELSE 'No' END AS active,
            notes
        FROM reserve_study_scenarios
        ORDER BY sort_order, scenario_name
    """,

    "fiscal_year_closes": """
        SELECT
            fyc.fiscal_year,
            fyc.closed_at,
            fyc.reopened_at,
            je_op.entry_number          AS operating_close_entry,
            je_res.entry_number         AS reserve_close_entry
        FROM fiscal_year_closes fyc
        LEFT JOIN journal_entries je_op  ON je_op.id  = fyc.closing_je_operating_id
        LEFT JOIN journal_entries je_res ON je_res.id = fyc.closing_je_reserve_id
        ORDER BY fyc.fiscal_year
    """,
}


# ── File-building helpers ────────────────────────────────────────────────────

def _build_file(headers: list[str], rows: list[tuple]) -> str:
    """
    Return the CSV file content as a string.

    Always comma-separated.  Any comma inside a cell value is replaced
    with the HTML entity &#x2C; so it is never mistaken for a delimiter.
    Newlines inside cell values are replaced with a space.
    """
    lines = [",".join(headers)]
    for row in rows:
        cells = []
        for v in row:
            s = "" if v is None else str(v)
            s = s.replace(",", "&#x2C;").replace("\n", " ").replace("\r", "")
            cells.append(s)
        lines.append(",".join(cells))
    return "\n".join(lines) + "\n"


# ── Page service ─────────────────────────────────────────────────────────────

@dataclass
class ExportPageResponse:
    status_code: int
    body_html: str


class ExportPages:
    """Render the export selection page and build ZIP downloads."""

    TEMPLATE = "export.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ── GET: show selection form ─────────────────────────────────────────

    def render_page(
        self,
        *,
        org: dict | None,
        theme: str,
        flash_message: str = "",
        error_message: str = "",
    ) -> ExportPageResponse:
        ctx = {
            "heading": "Export Data",
            "breadcrumb": "System",
            "org": org or {},
            "theme": theme,
            "page_key": "export",
            "export_types": EXPORT_TYPES,
            "export_groups": EXPORT_GROUPS,
            "flash_message": flash_message,
            "error_message": error_message,
        }
        return ExportPageResponse(
            status_code=HTTPStatus.OK,
            body_html=render_template(self.TEMPLATE, ctx),
        )

    # ── POST: build and return ZIP bytes ─────────────────────────────────

    def build_zip(self, selected_keys: list[str]) -> bytes:
        """
        Query each selected data set and pack the results into an
        in-memory ZIP archive.  Returns the raw ZIP bytes.
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for et in EXPORT_TYPES:
                key = et["key"]
                if key not in selected_keys:
                    continue
                sql = QUERIES.get(key, "")
                if not sql:
                    continue

                cursor = self.conn.execute(sql)
                headers = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
                content = _build_file(headers, rows)
                zf.writestr(f"{et['filename']}.csv", content.encode("utf-8"))

        buf.seek(0)
        return buf.read()

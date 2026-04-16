"""View-model shaping for formatted report summary rendering."""

from __future__ import annotations

from typing import Any


def build_summary_view_model(
    *,
    selected_report: str,
    api_payload: dict[str, object] | None,
) -> dict[str, Any]:
    """Build a template-friendly summary context for the selected report."""
    if not api_payload or api_payload.get("ok") is not True:
        return {
            "summary_template": "partials/summary_not_available.html",
            "summary": {"message": "No formatted summary available."},
        }

    data = api_payload.get("data")
    if not isinstance(data, dict):
        return {
            "summary_template": "partials/summary_not_available.html",
            "summary": {"message": "No formatted summary available."},
        }

    builders = {
        "trial-balance": _build_trial_balance_summary,
        "balance-sheet": _build_balance_sheet_summary,
        "income-statement": _build_income_statement_summary,
        "owner-ledger": _build_owner_ledger_summary,
        "ar-aging": _build_ar_aging_summary,
    }

    builder = builders.get(selected_report)
    if builder is None:
        return {
            "summary_template": "partials/summary_not_available.html",
            "summary": {
                "message": (
                    "No formatted summary available for this report yet. "
                    "See raw JSON below."
                )
            },
        }

    return builder(data)


def _build_trial_balance_summary(data: dict[str, object]) -> dict[str, Any]:
    rows = _safe_dict_list(data.get("rows"))
    return {
        "summary_template": "partials/summary_trial_balance.html",
        "summary": {
            "as_of_date": str(data.get("as_of_date", "")),
            "total_debits": str(data.get("total_debits", "")),
            "total_credits": str(data.get("total_credits", "")),
            "rows": [
                {
                    "account_number": str(row.get("account_number", "")),
                    "account_name": str(row.get("account_name", "")),
                    "debit_total": str(row.get("debit_total", "")),
                    "credit_total": str(row.get("credit_total", "")),
                    "net_debit": str(row.get("net_debit", "")),
                    "net_credit": str(row.get("net_credit", "")),
                }
                for row in rows
            ],
        },
    }


def _build_balance_sheet_summary(data: dict[str, object]) -> dict[str, Any]:
    return {
        "summary_template": "partials/summary_balance_sheet.html",
        "summary": {
            "as_of_date": str(data.get("as_of_date", "")),
            "total_assets": str(data.get("total_assets", "")),
            "total_liabilities": str(data.get("total_liabilities", "")),
            "total_equity": str(data.get("total_equity", "")),
            "balancing_difference": str(data.get("balancing_difference", "")),
            "assets": _build_account_section(data.get("assets")),
            "liabilities": _build_account_section(data.get("liabilities")),
            "equity": _build_account_section(data.get("equity")),
        },
    }


def _build_income_statement_summary(data: dict[str, object]) -> dict[str, Any]:
    return {
        "summary_template": "partials/summary_income_statement.html",
        "summary": {
            "from_date": str(data.get("from_date", "")),
            "to_date": str(data.get("to_date", "")),
            "total_income": str(data.get("total_income", "")),
            "total_expenses": str(data.get("total_expenses", "")),
            "net_income": str(data.get("net_income", "")),
            "income": _build_account_section(data.get("income")),
            "expenses": _build_account_section(data.get("expenses")),
        },
    }


def _build_owner_ledger_summary(data: dict[str, object]) -> dict[str, Any]:
    rows = _safe_dict_list(data.get("rows"))
    return {
        "summary_template": "partials/summary_owner_ledger.html",
        "summary": {
            "owner_name": str(data.get("owner_name", "")),
            "receivable_account_number": str(data.get("receivable_account_number", "")),
            "receivable_account_name": str(data.get("receivable_account_name", "")),
            "opening_balance": str(data.get("opening_balance", "")),
            "closing_balance": str(data.get("closing_balance", "")),
            "rows": [
                {
                    "entry_date": str(row.get("entry_date", "")),
                    "entry_number": str(row.get("entry_number", "")),
                    "source_type": str(row.get("source_type", "")),
                    "lot_number": str(row.get("lot_number", "")),
                    "due_date": str(row.get("due_date", "")),
                    "receipt_number": str(row.get("receipt_number", "")),
                    "debit_amount": str(row.get("debit_amount", "")),
                    "credit_amount": str(row.get("credit_amount", "")),
                    "running_balance": str(row.get("running_balance", "")),
                }
                for row in rows
            ],
        },
    }


def _build_ar_aging_summary(data: dict[str, object]) -> dict[str, Any]:
    owner_summaries = _safe_dict_list(data.get("owner_summaries"))
    detail_rows = _safe_dict_list(data.get("detail_rows"))

    return {
        "summary_template": "partials/summary_ar_aging.html",
        "summary": {
            "as_of_date": str(data.get("as_of_date", "")),
            "total_open_amount": str(data.get("total_open_amount", "")),
            "total_credit_balance": str(data.get("total_credit_balance", "")),
            "total_ledger_balance": str(data.get("total_ledger_balance", "")),
            "owner_summaries": [
                {
                    "owner_name": str(row.get("owner_name", "")),
                    "current_amount": str(row.get("current_amount", "")),
                    "amount_1_30": str(row.get("amount_1_30", "")),
                    "amount_31_60": str(row.get("amount_31_60", "")),
                    "amount_61_90": str(row.get("amount_61_90", "")),
                    "amount_90_plus": str(row.get("amount_90_plus", "")),
                    "total_open_amount": str(row.get("total_open_amount", "")),
                    "credit_balance": str(row.get("credit_balance", "")),
                    "ledger_balance": str(row.get("ledger_balance", "")),
                }
                for row in owner_summaries
            ],
            "detail_rows": [
                {
                    "owner_name": str(row.get("owner_name", "")),
                    "lot_number": str(row.get("lot_number", "")),
                    "assessment_id": str(row.get("assessment_id", "")),
                    "due_date": str(row.get("due_date", "")),
                    "aging_bucket": str(row.get("aging_bucket", "")),
                    "original_amount": str(row.get("original_amount", "")),
                    "applied_amount": str(row.get("applied_amount", "")),
                    "remaining_amount": str(row.get("remaining_amount", "")),
                }
                for row in detail_rows
            ],
        },
    }


def _build_account_section(section: object) -> dict[str, Any]:
    if not isinstance(section, dict):
        return {"rows": []}

    rows = _safe_dict_list(section.get("rows"))
    return {
        "rows": [
            {
                "account_number": str(row.get("account_number", "")),
                "account_name": str(row.get("account_name", "")),
                "fund_code": str(row.get("fund_code", "")),
                "amount": str(row.get("amount", "")),
            }
            for row in rows
        ]
    }


def _safe_dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
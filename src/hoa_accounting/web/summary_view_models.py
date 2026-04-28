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
        "owner-ledger": _build_owner_ledger_summary,
        "ar-aging": _build_ar_aging_summary,
        "ytd-expense-summary": _build_ytd_expense_summary,
        "expenses-by-date": _build_expenses_by_date_summary,
        "income-by-date": _build_income_by_date_summary,
        "deposits": _build_deposits_summary,
        "categories": _build_categories_summary,
        "bank-transactions": _build_bank_transactions_summary,
        "vendor-expenses": _build_vendor_expenses_summary,
        "homeowner-contact-list": _build_homeowner_contact_list_summary,
        "expenses-vs-budget": _build_expenses_vs_budget_summary,
        "budget-summary": _build_budget_summary_summary,
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
    raw_owners = _safe_dict_list(data.get("owners"))
    owners = [
        {
            "display_name": str(o.get("display_name", "")),
            "first_name":   str(o.get("first_name", "")),
            "last_name":    str(o.get("last_name", "")),
            "email":        str(o.get("email", "")),
            "phone":        str(o.get("phone", "")),
        }
        for o in raw_owners
    ]
    raw_ob_lines = _safe_dict_list(data.get("opening_balance_lines"))
    opening_balance_lines = [
        {
            "charge_type": str(line.get("charge_type", "")),
            "label":       str(line.get("label", "")),
            "amount":      str(line.get("amount", "")),
        }
        for line in raw_ob_lines
    ]
    return {
        "summary_template": "partials/summary_owner_ledger.html",
        "summary": {
            "lot_number": str(data.get("lot_number", "")),
            "lot_address": str(data.get("lot_address", "")),
            "owners": owners,
            "year": str(data.get("year", "")),
            "opening_balance": str(data.get("opening_balance", "")),
            "opening_balance_lines": opening_balance_lines,
            "closing_balance": str(data.get("closing_balance", "")),
            "rows": [
                {
                    "entry_date": str(row.get("entry_date", "")),
                    "entry_type": str(row.get("entry_type", "")),
                    "charge_type": str(row.get("charge_type", "")),
                    "description": str(row.get("description", "")),
                    "due_date": str(row.get("due_date", "")),
                    "debit_amount": str(row.get("debit_amount", "")),
                    "credit_amount": str(row.get("credit_amount", "")),
                    "running_balance": str(row.get("running_balance", "")),
                    "status": str(row.get("status", "")),
                    "receipt_number": str(row.get("receipt_number", "")),
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
                    "description": str(row.get("description", "")),
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


def _build_ytd_expense_summary(data: dict[str, object]) -> dict[str, Any]:
    groups_raw = _safe_dict_list(data.get("groups"))
    flat_rows: list[dict[str, Any]] = []
    for group in groups_raw:
        group_code = str(group.get("group_code", ""))
        for row in _safe_dict_list(group.get("rows")):
            flat_rows.append({
                "account_number": str(row.get("account_number", "")),
                "account_name":   str(row.get("account_name", "")),
                "group_code":     group_code,
                "ytd_amount":     str(row.get("ytd_amount", "")),
                "comment":        str(row.get("comment", "")),
            })
    return {
        "summary_template": "partials/summary_ytd_expense.html",
        "summary": {
            "from_date":    str(data.get("from_date", "")),
            "to_date":      str(data.get("to_date", "")),
            "grand_total":  str(data.get("grand_total", "")),
            "rows":         flat_rows,
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



def _build_expenses_by_date_summary(data: dict[str, object]) -> dict[str, Any]:
    rows = _safe_dict_list(data.get("rows"))
    return {
        "summary_template": "partials/summary_expenses_by_date.html",
        "summary": {
            "from_date": str(data.get("from_date", "")),
            "to_date": str(data.get("to_date", "")),
            "grand_total": str(data.get("grand_total", "")),
            "rows": [
                {
                    "entry_date": str(row.get("entry_date", "")),
                    "entry_number": str(row.get("entry_number", "")),
                    "account_number": str(row.get("account_number", "")),
                    "account_name": str(row.get("account_name", "")),
                    "group_code": str(row.get("group_code", "")),
                    "fund_code": str(row.get("fund_code", "")),
                    "memo": str(row.get("memo", "")),
                    "amount": str(row.get("amount", "")),
                }
                for row in rows
            ],
        },
    }


def _build_income_by_date_summary(data: dict[str, object]) -> dict[str, Any]:
    rows = _safe_dict_list(data.get("rows"))
    return {
        "summary_template": "partials/summary_income_by_date.html",
        "summary": {
            "from_date": str(data.get("from_date", "")),
            "to_date": str(data.get("to_date", "")),
            "grand_total": str(data.get("grand_total", "")),
            "rows": [
                {
                    "entry_date":   str(row.get("entry_date", "")),
                    "source":       str(row.get("source", "")),
                    "lot_number":   str(row.get("lot_number", "")),
                    "account_code": str(row.get("account_code", "")),
                    "account_name": str(row.get("account_name", "")),
                    "memo":         str(row.get("memo", "")),
                    "comment":      str(row.get("comment", "")),
                    "amount":       str(row.get("amount", "")),
                }
                for row in rows
            ],
        },
    }


def _build_bank_transactions_summary(data: dict[str, object]) -> dict[str, Any]:
    rows = _safe_dict_list(data.get("rows"))
    return {
        "summary_template": "partials/summary_bank_transactions.html",
        "summary": {
            "from_date":         str(data.get("from_date", "")),
            "to_date":           str(data.get("to_date", "")),
            "bank_account_name": str(data.get("bank_account_name") or "All accounts"),
            "total_in":          str(data.get("total_in", "")),
            "total_out":         str(data.get("total_out", "")),
            "rows": [
                {
                    "transaction_date":    str(row.get("transaction_date", "")),
                    "bank_account":        str(row.get("bank_account", "")),
                    "description":         str(row.get("description", "")),
                    "memo":                str(row.get("memo", "")),
                    "amount":              str(row.get("amount", "")),
                    "transaction_type":    str(row.get("transaction_type", "")),
                    "match_type":          str(row.get("match_type", "")),
                    "matched_source_type": str(row.get("matched_source_type", "")),
                    "matched_source_id":   str(row.get("matched_source_id", "")),
                    "validation_status":   str(row.get("validation_status", "")),
                    "rule_name":           str(row.get("rule_name", "")),
                }
                for row in rows
            ],
        },
    }


def _build_categories_summary(data: dict[str, object]) -> dict[str, Any]:
    rows = _safe_dict_list(data.get("rows"))
    # Group by category_type for display.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        ct = str(r.get("category_type", "OTHER"))
        grouped.setdefault(ct, []).append({
            "code":          str(r.get("code", "")),
            "name":          str(r.get("name", "")),
            "group_name":    str(r.get("group_name", "")),
            "fund_code":     str(r.get("fund_code", "")),
            "sort_order":    str(r.get("sort_order", "")),
            "active":        str(r.get("active", "")),
            "description":   str(r.get("description", "")),
        })
    # Stable ordering: INCOME, EXPENSE, TRANSFER, then anything else.
    ordered = [t for t in ("INCOME", "EXPENSE", "TRANSFER") if t in grouped]
    ordered += [t for t in grouped if t not in ordered]
    groups = [{"category_type": t, "rows": grouped[t]} for t in ordered]
    return {
        "summary_template": "partials/summary_categories.html",
        "summary": {
            "total_count": len(rows),
            "groups": groups,
        },
    }


def _build_deposits_summary(data: dict[str, object]) -> dict[str, Any]:
    rows = _safe_dict_list(data.get("rows"))
    return {
        "summary_template": "partials/summary_deposits.html",
        "summary": {
            "from_date":   str(data.get("from_date", "")),
            "to_date":     str(data.get("to_date", "")),
            "grand_total": str(data.get("grand_total", "")),
            "rows": [
                {
                    "batch_id":             str(row.get("batch_id", "")),
                    "deposit_date":         str(row.get("deposit_date", "")),
                    "bank_account":         str(row.get("bank_account", "")),
                    "bank_account_last4":   str(row.get("bank_account_last4", "")),
                    "total_amount":         str(row.get("total_amount", "")),
                    "journal_entry":        str(row.get("journal_entry", "")),
                    "memo":                 str(row.get("memo", "")),
                    "owner_payment_count":  str(row.get("owner_payment_count", "")),
                    "owner_payment_total":  str(row.get("owner_payment_total", "")),
                    "other_source_count":   str(row.get("other_source_count", "")),
                    "other_source_total":   str(row.get("other_source_total", "")),
                    "lines": [
                        {
                            "line_type":   str(line.get("line_type", "")),
                            "description": str(line.get("description", "")),
                            "detail":      str(line.get("detail", "")),
                            "reference":   str(line.get("reference", "")),
                            "amount":      str(line.get("amount", "")),
                        }
                        for line in _safe_dict_list(row.get("lines"))
                    ],
                }
                for row in rows
            ],
        },
    }


def _build_vendor_expenses_summary(data: dict[str, object]) -> dict[str, Any]:
    rows = _safe_dict_list(data.get("rows"))
    return {
        "summary_template": "partials/summary_vendor_expenses.html",
        "summary": {
            "from_date": str(data.get("from_date", "")),
            "to_date": str(data.get("to_date", "")),
            "vendor_name": str(data.get("vendor_name") or "All Vendors"),
            "grand_total": str(data.get("grand_total", "")),
            "rows": [
                {
                    "vendor_name": str(row.get("vendor_name", "")),
                    "entry_date": str(row.get("entry_date", "")),
                    "entry_number": str(row.get("entry_number", "")),
                    "account_number": str(row.get("account_number", "")),
                    "account_name": str(row.get("account_name", "")),
                    "group_code": str(row.get("group_code", "")),
                    "memo": str(row.get("memo", "")),
                    "amount": str(row.get("amount", "")),
                }
                for row in rows
            ],
        },
    }


def _build_homeowner_contact_list_summary(data: dict[str, object]) -> dict[str, Any]:
    rows = _safe_dict_list(data.get("rows"))
    return {
        "summary_template": "partials/summary_homeowner_contact_list.html",
        "summary": {
            "rows": [
                {
                    "role": str(row.get("role", "OWNER")),
                    "first_name": str(row.get("first_name", "")),
                    "last_name": str(row.get("last_name", "")),
                    "address": str(row.get("address", "")),
                    "cell_phone": str(row.get("cell_phone", "")),
                    "home_phone": str(row.get("home_phone", "")),
                    "email": str(row.get("email", "")),
                }
                for row in rows
            ],
        },
    }


def _build_expenses_vs_budget_summary(data: dict[str, object]) -> dict[str, Any]:
    groups_raw = _safe_dict_list(data.get("groups"))
    groups: list[dict[str, Any]] = []
    for group in groups_raw:
        rows = _safe_dict_list(group.get("rows"))
        groups.append({
            "group_code": str(group.get("group_code", "")),
            "group_budget": str(group.get("group_budget", "")),
            "group_actual": str(group.get("group_actual", "")),
            "group_variance": str(group.get("group_variance", "")),
            "rows": [
                {
                    "category_name": str(row.get("category_name", "")),
                    "group_code": str(row.get("group_code", "")),
                    "budget_amount": str(row.get("budget_amount", "")),
                    "actual_amount": str(row.get("actual_amount", "")),
                    "variance": str(row.get("variance", "")),
                }
                for row in rows
            ],
        })
    return {
        "summary_template": "partials/summary_expenses_vs_budget.html",
        "summary": {
            "fiscal_year": str(data.get("fiscal_year", "")),
            "fund_code": str(data.get("fund_code", "")),
            "from_date": str(data.get("from_date", "")),
            "to_date": str(data.get("to_date", "")),
            "total_budget": str(data.get("total_budget", "")),
            "total_actual": str(data.get("total_actual", "")),
            "total_variance": str(data.get("total_variance", "")),
            "groups": groups,
        },
    }


def _build_budget_summary_summary(data: dict[str, object]) -> dict[str, Any]:
    years = list(data.get("years", []))
    total_amounts = [str(a) for a in (data.get("total_amounts") or [])]
    total_pct_changes = list(data.get("total_pct_changes") or [])
    groups = []
    for g in _safe_dict_list(data.get("groups")):
        rows = []
        for row in _safe_dict_list(g.get("rows")):
            rows.append({
                "category_name": str(row.get("category_name", "")),
                "group_code":    str(row.get("group_code", "")),
                "year_amounts":  [str(a) for a in (row.get("year_amounts") or [])],
                "pct_changes":   list(row.get("pct_changes") or []),
            })
        groups.append({
            "group_code":           str(g.get("group_code", "")),
            "rows":                 rows,
            "subtotal_amounts":     [str(a) for a in (g.get("subtotal_amounts") or [])],
            "subtotal_pct_changes": list(g.get("subtotal_pct_changes") or []),
        })
    return {
        "summary_template": "partials/summary_budget_summary.html",
        "summary": {
            "years":              years,
            "groups":             groups,
            "total_amounts":      total_amounts,
            "total_pct_changes":  total_pct_changes,
        },
    }


def _safe_dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
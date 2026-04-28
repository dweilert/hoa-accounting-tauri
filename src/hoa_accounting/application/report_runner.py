"""Application-layer report runner."""

from __future__ import annotations

import datetime
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hoa_accounting.config.loader import load_config
from hoa_accounting.db.connection import connect_sqlite
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.reporting.ar_aging import ARAgingReportService
from hoa_accounting.reporting.budget_summary import BudgetSummaryReportService
from hoa_accounting.reporting.bank_transactions import BankTransactionsReportService
from hoa_accounting.reporting.categories import CategoriesReportService
from hoa_accounting.reporting.deposits import DepositsReportService
from hoa_accounting.reporting.expenses_by_date import ExpensesByDateReportService
from hoa_accounting.reporting.expenses_vs_budget import ExpenseVsBudgetReportService
from hoa_accounting.reporting.homeowner_contact_list import HomeownerContactListReportService
from hoa_accounting.reporting.income_by_date import IncomeByDateReportService
from hoa_accounting.reporting.lot_statement import LotStatementReportService
from hoa_accounting.reporting.serializers import to_plain_data
from hoa_accounting.reporting.vendor_expenses import VendorExpensesReportService
from hoa_accounting.reporting.ytd_expense_summary import YtdExpenseSummaryReportService


@dataclass(frozen=True)
class ReportResult:
    """Structured output from a report runner execution."""
    report_name: str
    parameters: dict[str, Any]
    data: dict[str, Any]


class ReportRunner:
    """Dispatch reporting requests to the correct report service."""

    def __init__(
        self,
        *,
        config_path: str | Path = "config.yaml",
        connection_factory: Callable[[], sqlite3.Connection] | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self._connection_factory = connection_factory

    def run(self, report_name: str, **params: Any) -> ReportResult:
        """Run a named report and return serialized structured data."""
        normalized_name = self._normalize_report_name(report_name)

        with self._open_connection() as conn:
            raw_report = self._run_with_connection(
                conn=conn,
                report_name=normalized_name,
                params=params,
            )

        return ReportResult(
            report_name=normalized_name,
            parameters=dict(params),
            data=to_plain_data(raw_report),
        )

    def _run_with_connection(
        self,
        *,
        conn: sqlite3.Connection,
        report_name: str,
        params: dict[str, Any],
    ) -> Any:
        if report_name == "owner-ledger":
            lot_id = self._require_int_param(params, "lot_id")
            year_str = str(params.get("year", "")).strip()
            year = int(year_str) if year_str else datetime.date.today().year
            return LotStatementReportService(conn).generate(
                lot_id=lot_id,
                year=year,
            )

        if report_name == "ar-aging":
            as_of_date = self._require_param(params, "as_of_date")
            return ARAgingReportService(conn).generate(as_of_date=as_of_date)

        if report_name == "ytd-expense-summary":
            from_date = self._require_param(params, "from_date")
            to_date = self._require_param(params, "to_date")
            return YtdExpenseSummaryReportService(conn).generate(
                from_date=from_date,
                to_date=to_date,
            )

        if report_name == "expenses-by-date":
            from_date = self._require_param(params, "from_date")
            to_date = self._require_param(params, "to_date")
            return ExpensesByDateReportService(conn).generate(
                from_date=from_date,
                to_date=to_date,
            )

        if report_name == "income-by-date":
            from_date = self._require_param(params, "from_date")
            to_date = self._require_param(params, "to_date")
            return IncomeByDateReportService(conn).generate(
                from_date=from_date,
                to_date=to_date,
            )

        if report_name == "categories":
            return CategoriesReportService(conn).generate()

        if report_name == "bank-transactions":
            from_date = self._require_param(params, "from_date")
            to_date = self._require_param(params, "to_date")
            ba_str = str(params.get("bank_account_id", "")).strip()
            ba_id = int(ba_str) if ba_str else None
            return BankTransactionsReportService(conn).generate(
                from_date=from_date, to_date=to_date, bank_account_id=ba_id,
            )

        if report_name == "deposits":
            from_date = self._require_param(params, "from_date")
            to_date = self._require_param(params, "to_date")
            return DepositsReportService(conn).generate(
                from_date=from_date,
                to_date=to_date,
            )

        if report_name == "vendor-expenses":
            from_date = self._require_param(params, "from_date")
            to_date = self._require_param(params, "to_date")
            vendor_id_str = str(params.get("vendor_id", "")).strip()
            vendor_id = int(vendor_id_str) if vendor_id_str else None
            return VendorExpensesReportService(conn).generate(
                from_date=from_date,
                to_date=to_date,
                vendor_id=vendor_id,
            )

        if report_name == "homeowner-contact-list":
            sort_by = params.get("sort_by", "name").strip() or "name"
            return HomeownerContactListReportService(conn).generate(sort_by=sort_by)

        if report_name == "budget-summary":
            current_year = int(
                (params.get("fiscal_year") or "").strip()
                or str(datetime.date.today().year)
            )
            years_mode = (params.get("years_mode") or "prev_current").strip() or "prev_current"
            return BudgetSummaryReportService(conn).generate(
                years_mode=years_mode,
                current_year=current_year,
            )

        if report_name == "expenses-vs-budget":
            fiscal_year = self._require_int_param(params, "fiscal_year")
            fund_code = self._require_param(params, "fund_code")
            return ExpenseVsBudgetReportService(conn).generate(
                fiscal_year=fiscal_year,
                fund_code=fund_code,
            )

        raise ValidationError(f"Unsupported report: {report_name}")

    @contextmanager
    def _open_connection(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection for one report run.

        A caller-supplied ``connection_factory`` is borrowed — the caller
        owns its lifecycle (tests reuse shared in-memory databases). When
        we opened the connection ourselves we close it on exit so the
        server doesn't leak a file descriptor per report.
        """
        if self._connection_factory is not None:
            yield self._connection_factory()
            return

        config = load_config(self.config_path)
        if config.database.type.lower() != "sqlite":
            raise ValidationError(
                f"Unsupported database type for report runner: {config.database.type}"
            )
        conn = connect_sqlite(config.database.path)
        try:
            yield conn
        finally:
            conn.close()

    def _require_param(self, params: dict[str, Any], name: str) -> str:
        value = params.get(name)
        if value is None or str(value).strip() == "":
            raise ValidationError(
                f"Missing required parameter '{name}' for report execution."
            )
        return str(value)

    def _require_int_param(self, params: dict[str, Any], name: str) -> int:
        value = params.get(name)
        if value is None or str(value).strip() == "":
            raise ValidationError(
                f"Missing required parameter '{name}' for report execution."
            )
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"Parameter '{name}' must be an integer."
            ) from exc

    def _normalize_report_name(self, report_name: str) -> str:
        normalized = report_name.strip().lower().replace("_", "-")
        if not normalized:
            raise ValidationError("Report name is required.")
        return normalized
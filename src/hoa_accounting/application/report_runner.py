"""Application-layer report runner."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hoa_accounting.config.loader import load_config
from hoa_accounting.db.connection import connect_sqlite
from hoa_accounting.exceptions import ValidationError
from hoa_accounting.reporting.ar_aging import ARAgingReportService
from hoa_accounting.reporting.balance_sheet import BalanceSheetReportService
from hoa_accounting.reporting.general_ledger import GeneralLedgerReportService
from hoa_accounting.reporting.income_statement import IncomeStatementReportService
from hoa_accounting.reporting.owner_ledger import OwnerLedgerReportService
from hoa_accounting.reporting.serializers import to_plain_data
from hoa_accounting.reporting.trial_balance import TrialBalanceReportService


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
        if report_name == "trial-balance":
            as_of_date = self._require_param(params, "as_of_date")
            return TrialBalanceReportService(conn).generate(as_of_date=as_of_date)

        if report_name == "general-ledger":
            account_id = self._require_int_param(params, "account_id")
            from_date = self._require_param(params, "from_date")
            to_date = self._require_param(params, "to_date")
            return GeneralLedgerReportService(conn).generate(
                account_id=account_id,
                from_date=from_date,
                to_date=to_date,
            )

        if report_name == "owner-ledger":
            owner_id = self._require_int_param(params, "owner_id")
            receivable_account_id = self._require_int_param(
                params,
                "receivable_account_id",
            )
            from_date = self._require_param(params, "from_date")
            to_date = self._require_param(params, "to_date")
            return OwnerLedgerReportService(conn).generate(
                owner_id=owner_id,
                receivable_account_id=receivable_account_id,
                from_date=from_date,
                to_date=to_date,
            )

        if report_name == "ar-aging":
            as_of_date = self._require_param(params, "as_of_date")
            receivable_account_id = self._require_int_param(
                params,
                "receivable_account_id",
            )
            return ARAgingReportService(conn).generate(
                as_of_date=as_of_date,
                receivable_account_id=receivable_account_id,
            )

        if report_name == "balance-sheet":
            as_of_date = self._require_param(params, "as_of_date")
            return BalanceSheetReportService(conn).generate(as_of_date=as_of_date)

        if report_name == "income-statement":
            from_date = self._require_param(params, "from_date")
            to_date = self._require_param(params, "to_date")
            return IncomeStatementReportService(conn).generate(
                from_date=from_date,
                to_date=to_date,
            )

        raise ValidationError(f"Unsupported report: {report_name}")

    def _open_connection(self):
        if self._connection_factory is not None:
            return self._connection_factory()

        config = load_config(self.config_path)
        if config.database.type.lower() != "sqlite":
            raise ValidationError(
                f"Unsupported database type for report runner: {config.database.type}"
            )
        return connect_sqlite(config.database.path)

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
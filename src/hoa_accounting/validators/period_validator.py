"""Validation for accounting periods."""

from __future__ import annotations

from typing import Optional

from hoa_accounting.exceptions import ClosedPeriodError, ValidationError
from hoa_accounting.repositories.periods_repo import PeriodsRepository
from hoa_accounting.repositories.year_end_close_repo import YearEndCloseRepository


class PeriodValidator:
    """Validation of posting dates against accounting periods."""

    def __init__(
        self,
        periods_repo: PeriodsRepository,
        year_end_close_repo: Optional[YearEndCloseRepository] = None,
    ) -> None:
        self.periods_repo = periods_repo
        self.year_end_close_repo = year_end_close_repo

    def require_open_period(self, entry_date: str) -> int:
        """Return the period id if open, otherwise raise."""
        row = self.periods_repo.get_period_for_date(entry_date)
        if row is None:
            raise ValidationError(f"No accounting period found for date {entry_date}")
        if int(row["is_closed"]) == 1:
            raise ClosedPeriodError(f"Accounting period is closed for date {entry_date}")
        # Block posting into a formally closed fiscal year even if the
        # individual period has somehow been reopened.
        if self.year_end_close_repo is not None:
            fiscal_year = int(row["fiscal_year"])
            if self.year_end_close_repo.is_fiscal_year_closed(fiscal_year):
                raise ClosedPeriodError(
                    f"Fiscal year {fiscal_year} has been formally closed. "
                    "Re-open it before posting."
                )
        return int(row["id"])

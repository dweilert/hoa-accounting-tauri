"""Validation for accounting periods."""

from __future__ import annotations

from hoa_accounting.exceptions import ClosedPeriodError, ValidationError
from hoa_accounting.repositories.periods_repo import PeriodsRepository


class PeriodValidator:
    """Validation of posting dates against accounting periods."""

    def __init__(self, periods_repo: PeriodsRepository) -> None:
        self.periods_repo = periods_repo

    def require_open_period(self, entry_date: str) -> int:
        """Return the period id if open, otherwise raise."""
        row = self.periods_repo.get_period_for_date(entry_date)
        if row is None:
            raise ValidationError(f"No accounting period found for date {entry_date}")
        if int(row["is_closed"]) == 1:
            raise ClosedPeriodError(f"Accounting period is closed for date {entry_date}")
        return int(row["id"])

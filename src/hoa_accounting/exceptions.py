"""Domain-specific exceptions for the HOA accounting engine."""


class AccountingError(Exception):
    """Base class for accounting-related errors."""


class ValidationError(AccountingError):
    """Raised when business or input validation fails."""


class ClosedPeriodError(AccountingError):
    """Raised when attempting to post to a closed accounting period."""


class UnbalancedJournalError(AccountingError):
    """Raised when journal entry lines are not balanced."""


class NotFoundError(AccountingError):
    """Raised when a required database record cannot be found."""

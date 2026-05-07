"""Domain-specific exceptions for the HOA accounting engine."""


class AccountingError(Exception):
    """Base class for accounting-related errors."""


class ValidationError(AccountingError):
    """Raised when business or input validation fails."""


class NotFoundError(AccountingError):
    """Raised when a required database record cannot be found."""

"""Validation of account types for specific transaction roles."""

from __future__ import annotations

from hoa_accounting.exceptions import ValidationError
from hoa_accounting.repositories.accounts_repo import AccountsRepository


class AccountRoleValidator:
    """Validate that an account is appropriate for a posting role."""

    def __init__(self, accounts_repo: AccountsRepository) -> None:
        self.accounts_repo = accounts_repo

    def _require_type(self, account_id: int, expected_type_id: int, role_label: str) -> None:
        row = self.accounts_repo.get_detail_by_id(account_id)
        if row is None:
            raise ValidationError(f"Account {account_id} was not found for role {role_label}.")
        actual_type_id = int(row["account_type_id"])
        if actual_type_id != expected_type_id:
            raise ValidationError(
                f"Account {account_id} is not valid for {role_label}. "
                f"Expected account_type_id={expected_type_id}, got {actual_type_id}."
            )

    def require_asset_account(self, account_id: int, role_label: str) -> None:
        """Require an asset account."""
        self._require_type(account_id, 1, role_label)

    def require_liability_account(self, account_id: int, role_label: str) -> None:
        """Require a liability account."""
        self._require_type(account_id, 2, role_label)

    def require_income_account(self, account_id: int, role_label: str) -> None:
        """Require an income account."""
        self._require_type(account_id, 4, role_label)

    def require_expense_account(self, account_id: int, role_label: str) -> None:
        """Require an expense account."""
        self._require_type(account_id, 5, role_label)

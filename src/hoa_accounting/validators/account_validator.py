"""Validation for posting accounts and fund codes."""

from __future__ import annotations

from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.models.enums import FundCode
from hoa_accounting.repositories.accounts_repo import AccountsRepository


class AccountValidator:
    """Validation of account state and supported fund codes."""

    def __init__(self, accounts_repo: AccountsRepository) -> None:
        self.accounts_repo = accounts_repo

    def require_active_account(self, account_id: int) -> None:
        """Raise if the account is missing or inactive."""
        row = self.accounts_repo.get_by_id(account_id)
        if row is None:
            raise NotFoundError(f"Account {account_id} was not found.")
        if int(row["is_active"]) != 1:
            raise ValidationError(f"Account {account_id} is inactive.")

    def require_active_account_with_fund(self, account_id: int) -> str:
        """Raise if inactive/missing; otherwise return the account's fund code."""
        row = self.accounts_repo.get_detail_by_id(account_id)
        if row is None:
            raise NotFoundError(f"Account {account_id} was not found.")
        if int(row["is_active"]) != 1:
            raise ValidationError(f"Account {account_id} is inactive.")
        return str(row["fund_code"])

    def require_valid_fund_code(self, fund_code: str) -> None:
        """Raise if the fund code is unsupported."""
        try:
            FundCode(fund_code)
        except ValueError as exc:
            raise ValidationError(f"Invalid fund code: {fund_code}") from exc

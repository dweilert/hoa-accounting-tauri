"""Configuration models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HOAConfig:
    """HOA identity settings."""
    name: str
    legal_name: str
    tax_id_federal: str
    tax_id_state: str


@dataclass(frozen=True)
class DatabaseConfig:
    """Database settings."""
    type: str
    path: str


@dataclass(frozen=True)
class AppConfig:
    """Application runtime settings."""
    environment: str
    debug: bool
    theme: str = "warm"


@dataclass(frozen=True)
class AccountingConfig:
    """Accounting defaults."""
    fiscal_year_start_month: int
    default_fund: str
    # GL account number that owner dues payments credit. Defaults to
    # 1100 (the seed chart's Accounts Receivable — Owners). Configurable
    # so a chart that later renames the account doesn't break the UI.
    dues_receivable_account_number: str = "1100"
    # GL account number credited when dues are billed. Defaults to
    # 4000 (the seed chart's Assessment Income — Operating).
    dues_income_account_number: str = "4000"
    resale_fee_default_amount: str = "175.00"
    resale_fee_income_account_number: str = "4070"


@dataclass(frozen=True)
class Config:
    """Top-level application configuration."""
    hoa: HOAConfig
    database: DatabaseConfig
    app: AppConfig
    accounting: AccountingConfig

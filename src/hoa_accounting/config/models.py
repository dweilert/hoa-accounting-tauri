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
    resale_fee_default_amount: str = "175.00"


@dataclass(frozen=True)
class Config:
    """Top-level application configuration."""

    hoa: HOAConfig
    database: DatabaseConfig
    app: AppConfig
    accounting: AccountingConfig

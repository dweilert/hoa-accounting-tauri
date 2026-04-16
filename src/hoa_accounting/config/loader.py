"""Configuration loader."""

from __future__ import annotations

from pathlib import Path

import yaml

from hoa_accounting.config.models import (
    AccountingConfig,
    AppConfig,
    Config,
    DatabaseConfig,
    HOAConfig,
)
from hoa_accounting.exceptions import ValidationError


def load_config(path: str | Path = "config.yaml") -> Config:
    """Load configuration from YAML."""
    config_path = Path(path)
    if not config_path.exists():
        raise ValidationError(f"Config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValidationError("Config file must contain a top-level mapping.")

    try:
        hoa_raw = raw["hoa"]
        database_raw = raw["database"]
        app_raw = raw["app"]
        accounting_raw = raw["accounting"]
    except KeyError as exc:
        raise ValidationError(f"Missing config section: {exc.args[0]}") from exc

    return Config(
        hoa=HOAConfig(**hoa_raw),
        database=DatabaseConfig(**database_raw),
        app=AppConfig(**app_raw),
        accounting=AccountingConfig(**accounting_raw),
    )

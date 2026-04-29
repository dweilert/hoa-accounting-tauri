"""Configuration loader."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import TypeVar, Any

import yaml

from hoa_accounting.config.models import (
    AccountingConfig,
    AppConfig,
    Config,
    DatabaseConfig,
    HOAConfig,
)
from hoa_accounting.exceptions import ValidationError


_T = TypeVar("_T")


def _build(cls: type[_T], raw: dict[str, Any]) -> _T:
    """Construct a dataclass, ignoring any extra keys in the YAML.

    Lets old config.yaml files keep stale fields (e.g. retired GL account
    numbers) without crashing config loading after those fields are dropped
    from the dataclass.
    """
    valid = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    filtered = {k: v for k, v in raw.items() if k in valid}
    return cls(**filtered)  # type: ignore[arg-type]


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
        hoa=_build(HOAConfig, hoa_raw),
        database=_build(DatabaseConfig, database_raw),
        app=_build(AppConfig, app_raw),
        accounting=_build(AccountingConfig, accounting_raw),
    )

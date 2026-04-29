"""Build the per-app ``org_context`` dict from config + DB.

The dict ends up on every template render via ``g.org`` so values that
appear in the sidebar / topbar (HOA name, theme, default dues amount)
read live from ``hoa_profile`` rather than the config file. The config
is the seed; the DB is the source of truth once setup runs.

Failure is intentionally lenient: a missing or malformed config file
yields safe placeholders so a fresh dev install can still render the
sidebar instead of 500-ing on every page.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import yaml

from hoa_accounting.config.loader import load_config


def load_org_context(config_path: Path) -> dict[str, Any]:
    """Pull the pieces of config templates want into a small dict.

    See module docstring for failure semantics.
    """
    try:
        config = load_config(config_path)
    except Exception:
        return {
            "name": "HOA Accounting",
            "legal_name": "",
            "environment": "local",
            "fiscal_year_start_month": 1,
            "theme": "warm",
        }
    # Try to read HOA names from the DB (editable via System Settings);
    # fall back to config.yaml values if the table is empty or missing.
    hoa_name = config.hoa.name
    hoa_legal = config.hoa.legal_name
    db_theme = getattr(config.app, "theme", "warm")
    db_dues = "0.00"
    db_freq = "annual"
    try:
        _c = sqlite3.connect(config.database.path)
        _c.row_factory = sqlite3.Row
        _row = _c.execute(
            "SELECT display_name, legal_name, theme, default_assessment_amount, default_billing_frequency FROM hoa_profile LIMIT 1"
        ).fetchone()
        if _row and _row["display_name"]:
            hoa_name = _row["display_name"]
        if _row and _row["legal_name"]:
            hoa_legal = _row["legal_name"]
        if _row and _row["theme"]:
            db_theme = _row["theme"]
        if _row and _row["default_assessment_amount"]:
            db_dues = _row["default_assessment_amount"]
        db_freq = (_row["default_billing_frequency"] if _row else None) or "annual"
        _c.close()
    except Exception:
        pass
    return {
        "name": hoa_name,
        "legal_name": hoa_legal,
        "environment": config.app.environment,
        "fiscal_year_start_month": config.accounting.fiscal_year_start_month,
        "theme": db_theme,
        "default_assessment_amount": db_dues,
        "default_billing_frequency": db_freq,
        "db_path": config.database.path,
        "resale_fee_default_amount": getattr(
            config.accounting, "resale_fee_default_amount", "175.00"
        ),
        "backup_config": (yaml.safe_load(Path(config_path).read_text()) or {}).get(
            "backup"
        )
        or {},
    }

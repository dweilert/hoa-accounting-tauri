"""Configuration loader tests."""

from __future__ import annotations

from pathlib import Path

from hoa_accounting.config.loader import load_config


def test_load_config(tmp_path: Path) -> None:
    """Config loader reads expected values."""
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
hoa:
  name: "Test HOA"
  legal_name: "Test HOA, Inc."
  tax_id_federal: "11-1111111"
  tax_id_state: "TX-1"

database:
  type: "sqlite"
  path: "./data/test.db"

app:
  environment: "local"
  debug: true

accounting:
  fiscal_year_start_month: 1
  default_fund: "OPERATING"
""",
        encoding="utf-8",
    )

    config = load_config(config_file)
    assert config.hoa.name == "Test HOA"
    assert config.database.path == "./data/test.db"
    assert config.accounting.default_fund == "OPERATING"

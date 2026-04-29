"""CSV parsing + primitive coercion helpers for the import pipeline.

Pure helpers — no DB, no Flask. Lives here so the per-data-type
inserters in :mod:`hoa_accounting.web.import_inserters` can share them
without importing ``import_pages``.
"""

from __future__ import annotations

import csv
import io


def parse_csv(content: str) -> tuple[list[str], list[list[str]]]:
    """Parse CSV content, accepting both:
      • Standard quoted CSV (Excel, Google Sheets, etc.)
      • Our ``&#x2C;``-encoded format (exported by this app)

    Returns ``(headers, data_rows)``.
    """
    reader = csv.reader(io.StringIO(content.strip()))
    all_rows = list(reader)
    if not all_rows:
        return [], []
    headers = [h.strip().replace("&#x2C;", ",") for h in all_rows[0]]
    data_rows = [
        [cell.replace("&#x2C;", ",") for cell in row]
        for row in all_rows[1:]
        if any(cell.strip() for cell in row)  # skip blank lines
    ]
    return headers, data_rows


def parse_bool(v: str, default: int = 1) -> int:
    """Coerce a CSV-style truthy/falsy string to ``0`` / ``1``."""
    s = v.strip().lower()
    if s in {"yes", "y", "true", "1"}:
        return 1
    if s in {"no", "n", "false", "0"}:
        return 0
    return default

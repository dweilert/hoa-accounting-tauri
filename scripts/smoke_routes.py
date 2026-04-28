#!/usr/bin/env python3
"""Hit every registered GET route via Flask's test_client; flag any 500s.

Usage:
    python scripts/smoke_routes.py [config.yaml]

Exits 1 on any 500 response, 0 if every route returns < 500. Designed to
catch the kinds of "page that nobody's looked at since the schema change"
errors that this codebase has accumulated over the Chart-of-Accounts
removal.

Routes with ``<int:foo>`` placeholders are filled in from real IDs in the
configured database (first row per table); routes whose required ID has
no row in the DB are skipped with a note.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

# Make ``src/`` importable when running from the repo root.
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "src"))

from hoa_accounting.config.loader import load_config  # noqa: E402
from hoa_accounting.web.app import create_app  # noqa: E402


# Map a Flask route placeholder name → which DB table to draw an ID from.
_PLACEHOLDER_TABLES: dict[str, str | None] = {
    "lot_id": "lots",
    "owner_id": "owners",
    "vendor_id": "vendors",
    "bank_account_id": "bank_accounts",
    "category_id": "categories",
    "budget_id": "budgets",
    "reconciliation_id": "bank_reconciliations",
    "vendor_bill_id": "vendor_bills",
    "income_batch_id": "income_batches",
    "batch_id": "bank_import_batches",
    "bank_txn_id": "bank_transactions",
    "asset_id": "reserve_assets",
    "scenario_id": "reserve_study_scenarios",
    "member_id": "board_members",
    "transfer_id": "reserve_transfers",
    "period_id": "accounting_periods",
    "rule_id": "bank_transaction_rules",
    "payment_id": "payments",
    "assessment_id": "assessments",
    "user_id": "local_users",
    "uid": "local_users",
    "renter_id": "lot_renters",
    # Bill Templates retired — tables/routes gone, so this stays None.
    "template_id": None,
}


def _first_id(conn: sqlite3.Connection, table: str | None) -> int | None:
    if not table:
        return None
    try:
        row = conn.execute(f"SELECT id FROM {table} ORDER BY id LIMIT 1").fetchone()
        return int(row[0]) if row else None
    except sqlite3.OperationalError:
        return None


def _resolve(rule: str, ids: dict[str, int]) -> str | None:
    """Substitute placeholders in a Flask rule with real IDs.

    Returns the concrete URL, or None if any required placeholder has no
    available ID.
    """
    placeholders = re.findall(r"<(?:int:|path:)?([^>]+)>", rule)
    out = rule
    for ph in placeholders:
        if ph not in ids:
            return None  # unknown placeholder — skip route
        out = re.sub(rf"<(?:int:|path:)?{re.escape(ph)}>", str(ids[ph]), out, count=1)
    return out


def main(argv: list[str]) -> int:
    cfg_path = argv[1] if len(argv) > 1 else "config.yaml"
    cfg = load_config(cfg_path)

    # Fetch real IDs for parameterized routes.
    conn = sqlite3.connect(cfg.database.path)
    ids: dict[str, int] = {}
    for ph, table in _PLACEHOLDER_TABLES.items():
        v = _first_id(conn, table)
        if v is not None:
            ids[ph] = v
    conn.close()

    app = create_app(cfg_path)
    client = app.test_client()

    # Collect all GET routes (Flask's url_map gives us the canonical list).
    routes: list[str] = []
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods:
            continue
        if rule.rule.startswith("/static"):
            continue
        if rule.rule == "/favicon.ico":
            continue
        routes.append(rule.rule)

    routes.sort()
    failures: list[tuple[str, int]] = []
    skipped: list[str] = []
    ok = 0

    for rule in routes:
        url = _resolve(rule, ids)
        if url is None:
            skipped.append(rule)
            continue
        resp = client.get(url, follow_redirects=False)
        if resp.status_code >= 500:
            failures.append((url, resp.status_code))
        else:
            ok += 1

    print(f"Smoke test: {ok} OK · {len(failures)} failed · {len(skipped)} skipped "
          f"(no test data) · {len(routes)} total")
    if failures:
        print("\nFailures (>= 500):")
        for url, status in failures:
            print(f"  [{status}] {url}")
    if skipped:
        print("\nSkipped (no row in DB to substitute the URL placeholder):")
        for rule in skipped:
            print(f"  {rule}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

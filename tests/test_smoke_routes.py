"""Smoke test: every registered GET route must not return 500.

Catches regressions like "page references a column that was just dropped"
or "template still expects context vars from the old schema". Cheap and
fast to run; if anything starts 500ing the test fails immediately and
points at the URL.

Routes with ``<int:foo>`` placeholders are filled in from real IDs in
the configured database (first row per table). Routes whose required
ID has no row in the DB are reported as skips, not failures.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from hoa_accounting.config.loader import load_config
from hoa_accounting.web.app import create_app

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
    except sqlite3.OperationalError:
        return None
    return int(row[0]) if row else None


def _resolve(rule: str, ids: dict[str, int]) -> str | None:
    placeholders = re.findall(r"<(?:int:|path:)?([^>]+)>", rule)
    out = rule
    for ph in placeholders:
        if ph not in ids:
            return None
        out = re.sub(rf"<(?:int:|path:)?{re.escape(ph)}>", str(ids[ph]), out, count=1)
    return out


def _config_path() -> Path:
    """Use the repo's config.yaml if present, otherwise skip the suite.

    A typical pytest CI run won't have a real config — this lets the
    suite live in the repo without breaking environments where it can't
    be run. Local devs and the post-deploy smoke job run with the real
    file present and get full coverage.
    """
    path = Path(__file__).resolve().parent.parent / "config.yaml"
    return path


@pytest.fixture(scope="module")
def smoke_app():
    cfg_path = _config_path()
    if not cfg_path.exists():
        pytest.skip(
            f"No config.yaml at {cfg_path} — smoke suite needs the live app config."
        )
    cfg = load_config(str(cfg_path))
    if not Path(cfg.database.path).exists():
        pytest.skip(f"Configured database missing: {cfg.database.path}")
    return create_app(str(cfg_path)), cfg


@pytest.fixture(scope="module")
def smoke_ids(smoke_app):
    _, cfg = smoke_app
    conn = sqlite3.connect(cfg.database.path)
    try:
        ids: dict[str, int] = {}
        for ph, table in _PLACEHOLDER_TABLES.items():
            v = _first_id(conn, table)
            if v is not None:
                ids[ph] = v
        return ids
    finally:
        conn.close()


def _all_get_rules(app) -> list[str]:
    rules: list[str] = []
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods:
            continue
        if rule.rule.startswith("/static"):
            continue
        if rule.rule == "/favicon.ico":
            continue
        rules.append(rule.rule)
    return sorted(rules)


def _login_as_admin(client) -> None:
    """Skip the login form by writing an admin session directly. Lets the
    smoke test exercise authenticated routes without round-tripping the
    real login flow.
    """
    with client.session_transaction() as sess:
        sess["user"] = {
            "email": "smoke-admin@test.local",
            "display_name": "Smoke Tester",
            "role": "admin",
            "backend": "local",
            "groups": [],
        }


def test_no_route_returns_500(smoke_app, smoke_ids):
    app, _cfg = smoke_app
    client = app.test_client()
    _login_as_admin(client)
    failures: list[tuple[str, int]] = []
    skipped: list[str] = []
    ok = 0

    for rule in _all_get_rules(app):
        url = _resolve(rule, smoke_ids)
        if url is None:
            skipped.append(rule)
            continue
        resp = client.get(url, follow_redirects=False)
        if resp.status_code >= 500:
            failures.append((url, resp.status_code))
        else:
            ok += 1

    if failures:
        msg = "Routes returning 5xx:\n" + "\n".join(f"  [{s}] {u}" for u, s in failures)
        pytest.fail(msg)

    # Surface skips in test output without failing.
    print(f"\n[smoke] {ok} OK · {len(skipped)} skipped (no DB rows for placeholders)")

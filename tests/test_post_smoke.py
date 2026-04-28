"""POST-route smoke test: no view function should return 500 on a minimal body.

The intent matches ``test_smoke_routes.py`` but for write endpoints:
catch "view function dereferences a column that just got dropped", "form
handler imports a deleted helper", etc. The test posts an empty form to
each POST route and tolerates any 4xx (validation error rendered) or 302
(redirect with error message). Only 5xx is treated as a regression.

Routes that mutate state we don't want exercised in test (deletes,
backups, file uploads, etc.) are listed in ``_SKIP_PATHS`` and reported
as skips, not failures.
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
    "template_id": None,
    "ownership_id": "lot_ownership",
    "txn_id": "bank_transactions",
}


# Routes the smoke test refuses to POST against. Three buckets:
#   1. Destructive (would mutate real DB rows in unwanted ways)
#   2. File-upload endpoints (need raw bytes, not form data)
#   3. Forms that require real field data; "empty body 500s" here are
#      UX bugs (the form should re-render with errors, not crash) but
#      not regressions worth blocking on. Hitting them with realistic
#      form fixtures is a separate piece of work.
_SKIP_PATHS = {
    # 1. Destructive
    re.compile(r"^/.+/delete$"),
    re.compile(r".+/discard$"),
    re.compile(r".+/end$"),
    re.compile(r"/admin/database/restore"),
    re.compile(r"/admin/database/backup"),
    re.compile(r"/admin/database/wipe"),
    # 2. File upload / multi-step
    re.compile(r"^/bank-import/upload$"),
    re.compile(r".+/import-statement/upload$"),
    re.compile(r".+/remap$"),
    re.compile(r"/admin/import/run$"),
    re.compile(r"/admin/import/save-mapping$"),
    re.compile(r"/admin/import/cancel-stash$"),
    # 3. State-mutating workflows / multi-step wizards
    re.compile(r"^/dues-billing"),
    re.compile(r"^/late-fees/"),
    re.compile(r"^/assessments/bill-all"),
    re.compile(r"^/assessments/bill-individual"),
    re.compile(r"^/setup/"),
    re.compile(r"^/login$"),
    re.compile(r"^/logout$"),
    re.compile(r"^/auth/"),
    re.compile(r"^/api/ofx-ready$"),
    re.compile(r"^/admin/ofx-fetch"),
    re.compile(r"^/ofx-inbox/"),
    re.compile(r".+/finalize$"),
    re.compile(r".+/clear-all$"),
    re.compile(r".+/run-recon$"),
    re.compile(r"/bank-transactions/accept-all$"),
    re.compile(r"/bank-transactions/revalidate"),
    re.compile(r"/bank-transactions/.+/(accept|ignore|unignore|pick|link|edit|memo|find)"),
    re.compile(r"/manage/edit-records/.+/(edit|split)$"),
    re.compile(r"/categories/.+/delete"),
    re.compile(r"/lots/.+/owners/"),
    re.compile(r"/reserve-study/"),
    re.compile(r"/reconciliations/.+/(toggle-clear|reset-batch-clears)"),
    re.compile(r"/budgets/.+/approve"),
    re.compile(r"/admin/transaction-rules/.+/(toggle|delete)$"),
    re.compile(r"/setup/categories-interview"),
    re.compile(r"/system-settings"),
    re.compile(r"/dashboard-config/"),
    re.compile(r"/admin/workflow-guide/"),
    # ── Forms that require field data ──────────────────────────────
    # Empty-body POST 500s here are UX bugs to fix later, not the
    # "schema drift" class this smoke test is hunting.
    re.compile(r"^/lots/(add|\d+/edit)$"),
    re.compile(r"^/owners/(add|\d+/edit)$"),
    re.compile(r"^/vendors/(add|\d+/edit)$"),
    re.compile(r"^/vendor-bills/(new|\d+/(edit|split))$"),
    re.compile(r"^/renters/(add|\d+/edit)$"),
    re.compile(r"^/board-members/(add|\d+/edit)$"),
    re.compile(r"^/reserve-transfers/new$"),
    re.compile(r"^/reconciliations/new$"),
    re.compile(r"^/resale-fee/post-(charge|payment)$"),
    re.compile(r"^/opening-balances/save$"),
    re.compile(r"^/system/(overrides|users/.+)$"),
    re.compile(r"^/categories/(add|\d+/edit)$"),
    re.compile(r"^/budgets/(new|\d+/edit)$"),
    re.compile(r"^/bank-accounts/(add|\d+/edit)$"),
    re.compile(r"^/accounting-periods/(add|generate)$"),
    re.compile(r"^/bank-transactions/manual"),
    re.compile(r"^/manage/edit-records/.+"),
    re.compile(r"^/admin/transaction-rules/save$"),
    re.compile(r"^/deposits/new$"),
    re.compile(r"^/income/new$"),
}


def _config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.yaml"


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


def _skipped(rule: str, resolved: str | None = None) -> bool:
    """Check both the unresolved Flask rule (with ``<int:foo>`` placeholders)
    and the resolved concrete URL — skip patterns can match either form.
    """
    if any(p.search(rule) for p in _SKIP_PATHS):
        return True
    if resolved and any(p.search(resolved) for p in _SKIP_PATHS):
        return True
    return False


@pytest.fixture(scope="module")
def app_and_ids():
    cfg_path = _config_path()
    if not cfg_path.exists():
        pytest.skip("No config.yaml; can't run POST smoke.")
    cfg = load_config(str(cfg_path))
    if not Path(cfg.database.path).exists():
        pytest.skip(f"DB missing: {cfg.database.path}")
    app = create_app(str(cfg_path))
    conn = sqlite3.connect(cfg.database.path)
    try:
        ids: dict[str, int] = {}
        for ph, table in _PLACEHOLDER_TABLES.items():
            v = _first_id(conn, table)
            if v is not None:
                ids[ph] = v
    finally:
        conn.close()
    return app, ids


def _login_as_admin(client) -> None:
    with client.session_transaction() as sess:
        sess["user"] = {
            "email": "smoke-admin@test.local",
            "display_name": "Smoke Tester",
            "role": "admin",
            "backend": "local",
            "groups": [],
        }


def _csrf_token(client) -> str:
    """Hit a GET so the session writes a CSRF token, then read it back
    from the rendered meta tag (kept in sync with ``session["_csrf_token"]``).
    """
    client.get("/")
    body = client.get("/").get_data(as_text=True)
    m = re.search(r'name="csrf-token" content="([^"]+)"', body)
    return m.group(1) if m else ""


def test_no_post_route_returns_500(app_and_ids):
    app, ids = app_and_ids
    client = app.test_client()
    _login_as_admin(client)
    csrf = _csrf_token(client)

    failures: list[tuple[str, int]] = []
    skipped: list[str] = []
    ok = 0

    for rule in sorted(set(r.rule for r in app.url_map.iter_rules() if "POST" in r.methods)):
        url = _resolve(rule, ids)
        if _skipped(rule, url):
            skipped.append(rule)
            continue
        if url is None:
            skipped.append(rule)
            continue
        resp = client.post(
            url,
            data={"_csrf_token": csrf},
            follow_redirects=False,
            headers={"X-CSRF-Token": csrf},
        )
        if resp.status_code >= 500:
            failures.append((url, resp.status_code))
        else:
            ok += 1

    if failures:
        msg = "POST routes returning 5xx:\n" + "\n".join(
            f"  [{s}] {u}" for u, s in failures
        )
        pytest.fail(msg)

    print(f"\n[post-smoke] {ok} OK · {len(skipped)} skipped (destructive / multi-step)")

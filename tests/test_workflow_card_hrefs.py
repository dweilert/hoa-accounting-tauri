"""Every active ``workflow_cards.href`` must resolve to a real route.

Catches the failure mode that bit us when the COA-era hrefs (`/journal-entry-new`,
`/account-ledger`, etc.) became 404s after the schema cleanup. Cheap and
fast — the assertion is just "every href maps to a registered URL rule".

Skipped automatically when there's no live config / DB to read from.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from hoa_accounting.config.loader import load_config
from hoa_accounting.web.app import create_app


def _config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.yaml"


@pytest.fixture(scope="module")
def app_and_db():
    cfg_path = _config_path()
    if not cfg_path.exists():
        pytest.skip("No config.yaml; can't validate workflow hrefs.")
    cfg = load_config(str(cfg_path))
    if not Path(cfg.database.path).exists():
        pytest.skip(f"DB missing: {cfg.database.path}")
    return create_app(str(cfg_path)), cfg


def _route_matchers(app) -> list[re.Pattern[str]]:
    """Compile every GET route into a regex so we can match real hrefs
    (with concrete IDs filled in) against them.
    """
    out: list[re.Pattern[str]] = []
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods:
            continue
        # Replace <int:foo> / <path:foo> placeholders with regex.
        pat = re.sub(r"<int:[^>]+>", r"\\d+", rule.rule)
        pat = re.sub(r"<path:[^>]+>", r".+", pat)
        pat = re.sub(r"<[^>]+>", r"[^/]+", pat)
        out.append(re.compile("^" + pat + "$"))
    return out


def test_every_active_workflow_card_href_resolves(app_and_db):
    app, cfg = app_and_db
    matchers = _route_matchers(app)

    conn = sqlite3.connect(cfg.database.path)
    try:
        cards = conn.execute(
            "SELECT id, title, href FROM workflow_cards "
            "WHERE is_active = 1 AND href IS NOT NULL AND href != '' AND href != '#'"
        ).fetchall()
    finally:
        conn.close()

    broken: list[str] = []
    for cid, title, href in cards:
        # Strip any query string before matching against route patterns.
        path = href.split("?", 1)[0].rstrip("/") or "/"
        if not any(m.match(path) for m in matchers):
            broken.append(f"  [{cid}] {title!r} → {href}")

    if broken:
        pytest.fail(
            "workflow_cards reference URLs with no matching route:\n"
            + "\n".join(broken)
        )

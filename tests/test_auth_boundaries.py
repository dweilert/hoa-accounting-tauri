"""Auth + CSRF boundary tests.

The audit flagged two zero-coverage gaps that are cheap to close:

- **Auth boundary**: every test in this suite logs in as ``role="admin"``,
  so a regression that drops privilege checks would never surface.
- **CSRF**: the ``_enforce_csrf`` ``before_request`` hook in
  :py:mod:`hoa_accounting.web.app` is never exercised by a deliberately
  bad request — passing tests prove tokens are accepted but not that
  missing/wrong tokens are rejected.

This file adds one test for each. They use the real config-driven app
the way the smoke tests do, but post against routes chosen for
clarity (``/admin/database/check`` for the admin boundary,
``/categories/add`` for the CSRF boundary).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hoa_accounting.config.loader import load_config
from hoa_accounting.web.app import create_app


def _config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config.yaml"


@pytest.fixture(scope="module")
def app():
    cfg_path = _config_path()
    if not cfg_path.exists():
        pytest.skip("No config.yaml; can't run auth-boundary tests.")
    cfg = load_config(str(cfg_path))
    if not Path(cfg.database.path).exists():
        pytest.skip(f"DB missing: {cfg.database.path}")
    return create_app(str(cfg_path))


def _seat_user(client, *, role: str) -> None:
    with client.session_transaction() as sess:
        sess["user"] = {
            "email": f"boundary-{role}@test.local",
            "display_name": f"Boundary {role}",
            "role": role,
            "backend": "local",
            "groups": [],
        }


def _csrf_token(client) -> str:
    client.get("/")
    body = client.get("/").get_data(as_text=True)
    m = re.search(r'name="csrf-token" content="([^"]+)"', body)
    return m.group(1) if m else ""


def test_non_admin_blocked_from_admin_route(app):
    """A logged-in reports-only user POSTing an admin-only route must be
    rejected by the auth guard, not allowed through to the handler.

    /admin/database/check is the chosen target because its handler has
    no preconditions: if the guard were bypassed, the response would
    succeed (200) and we'd see DB stats — instead, the auth guard
    should return 403.
    """
    client = app.test_client()
    _seat_user(client, role="reports")
    csrf = _csrf_token(client)

    resp = client.post(
        "/admin/database/check",
        data={"_csrf_token": csrf},
        headers={"X-CSRF-Token": csrf},
        follow_redirects=False,
    )
    assert resp.status_code == 403, (
        f"Reports-only user reached admin route — got {resp.status_code}, "
        f"expected 403. Body head: {resp.data[:200]!r}"
    )


def test_post_without_csrf_token_rejected(app):
    """A state-mutating POST without a CSRF token must be rejected with
    403, regardless of the user's auth state. The ``_enforce_csrf``
    before_request hook in app.py owns this.
    """
    client = app.test_client()
    _seat_user(client, role="admin")

    # Don't fetch a CSRF token; submit form-data with no _csrf_token.
    resp = client.post(
        "/categories/add",
        data={
            "code": "CSRF_TEST",
            "name": "should-not-land",
            "category_type": "EXPENSE",
            "fund_code": "OPERATING",
            "active_flag": "1",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 403, (
        f"POST without CSRF token was not rejected — got {resp.status_code}. "
        f"Body head: {resp.data[:200]!r}"
    )

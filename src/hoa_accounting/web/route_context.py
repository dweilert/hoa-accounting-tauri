"""Shared context for route Blueprints.

The legacy ``create_app()`` defined every route as a closure over
``org_context``, ``_open_db()``, and a fleet of ``_open_*_pages()``
factories. As routes get split into per-area Blueprints, those
closures need somewhere to live; ``RouteContext`` is that home.

A Blueprint module asks for a ``RouteContext`` instance and uses it
to open per-request DB connections and read org-level config. Anything
more elaborate (e.g., a Pages-class factory) belongs in the
Blueprint module itself — keeping this surface narrow makes it easy
to test and reason about.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from flask import g

from hoa_accounting.db.connection import connect_sqlite


class RouteContext:
    """Per-request services shared across Blueprints.

    Construction is per-app (not per-request); each route accesses the
    request-scoped DB connection through :py:meth:`open_db`, which
    matches the legacy ``_open_db()`` closure exactly.
    """

    def __init__(
        self,
        *,
        org_context: dict[str, Any],
        report_page_service: Any | None = None,
    ) -> None:
        self.org_context = org_context
        self.report_page_service = report_page_service

    @property
    def theme(self) -> str:
        return str(self.org_context.get("theme", "warm"))

    def open_db(self) -> sqlite3.Connection:
        """Return the per-request shared DB connection, creating on first call.

        Mirrors the ``_open_db()`` closure that previously lived inside
        ``create_app()``: caches the connection on ``flask.g``, registers
        the ``audit_user`` UDF for audit-log triggers, and returns a
        single connection for the lifetime of the request.
        """
        if hasattr(g, "db"):
            return g.db  # type: ignore[no-any-return]
        db_path = self.org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = connect_sqlite(str(db_path))
        try:
            user = getattr(g, "current_user", None)
            email = user.email if user else "system"
            conn.create_function("audit_user", 0, lambda: email)
        except Exception:
            pass
        g.db = conn
        return conn

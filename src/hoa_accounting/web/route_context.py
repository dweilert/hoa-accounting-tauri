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
from typing import Any, TypeVar

from flask import g

from hoa_accounting.db.connection import connect_sqlite

P = TypeVar("P")


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

        Caches the connection on ``flask.g`` and returns a single connection
        for the lifetime of the request.
        """
        if hasattr(g, "db"):
            return g.db  # type: ignore[no-any-return]
        db_path = self.org_context.get("db_path")
        if not db_path:
            raise RuntimeError("database.path missing from config.")
        conn = connect_sqlite(str(db_path))
        g.db = conn
        return conn

    def open_pages(self, page_cls: type[P]) -> P:
        """Instantiate a Pages class with the per-request DB connection.

        Most ``Pages`` classes accept a single ``conn`` argument; the
        legacy per-blueprint ``_open_<area>_pages()`` factories all
        followed that shape. This helper collapses 34 of those factories
        into one call site:

            pages = ctx.open_pages(VendorPages)

        For the few factories that need extra construction logic
        (e.g. ``DashboardPages`` takes a fiscal year), keep the local
        factory rather than forcing it through this helper.
        """
        return page_cls(self.open_db())  # type: ignore[call-arg]

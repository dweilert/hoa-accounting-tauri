"""First-time setup wizard routes.

Five POST endpoints + one GET, each delegating directly to
:py:class:`~hoa_accounting.web.setup_pages.SetupPages`. The wizard
lives at ``/setup/*``; the global ``_setup_guard`` before-request hook
in ``app.py`` redirects every unauthenticated request to ``/setup``
until first-time setup completes.
"""

from __future__ import annotations

from flask import Blueprint, Response
from flask.typing import ResponseReturnValue

from hoa_accounting.web.route_context import RouteContext
from hoa_accounting.web.setup_pages import SetupPages


def make_setup_blueprint(ctx: RouteContext) -> Blueprint:
    bp = Blueprint("setup", __name__)
    db_path = str(ctx.org_context.get("db_path") or "")
    pages = SetupPages(db_path, ctx.org_context)

    @bp.get("/setup")
    def setup_get() -> ResponseReturnValue:
        return pages.get_setup()

    @bp.post("/setup/admin")
    def setup_post_admin() -> ResponseReturnValue:
        return pages.post_admin()

    @bp.post("/setup/login")
    def setup_post_login() -> ResponseReturnValue:
        return pages.post_login()

    @bp.post("/setup/identity")
    def setup_post_identity() -> ResponseReturnValue:
        return pages.post_identity()

    @bp.post("/setup/assessment")
    def setup_post_assessment() -> ResponseReturnValue:
        return pages.post_assessment()

    return bp

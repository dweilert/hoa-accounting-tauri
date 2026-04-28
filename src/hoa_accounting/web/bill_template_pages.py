"""Bill Templates — feature retired with the Chart of Accounts removal.

The original page depended on `expense_account_id` / `payable_account_id`
on `bill_templates`, which were dropped in migration 0061. This module
remains as a stub so existing routes still resolve to a friendly
placeholder rather than 500ing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from http import HTTPStatus


@dataclass(frozen=True)
class BillTemplatePageResponse:
    status_code: int
    body_html: str


_PLACEHOLDER = (
    "<!doctype html><html><body style='font-family:sans-serif;padding:2rem;'>"
    "<h1>Bill Templates</h1>"
    "<p>This feature was retired alongside the Chart of Accounts cleanup. "
    "Recurring bills can be entered directly under Vendor Bills.</p>"
    "<p><a href='/'>Back to dashboard</a></p>"
    "</body></html>"
)


class BillTemplatePages:
    def __init__(self, conn: sqlite3.Connection) -> None:  # noqa: ARG002
        pass

    def render_list(self, **_):  # type: ignore[no-untyped-def]
        return BillTemplatePageResponse(HTTPStatus.OK, _PLACEHOLDER)

    def render_form(self, **_):  # type: ignore[no-untyped-def]
        return BillTemplatePageResponse(HTTPStatus.OK, _PLACEHOLDER)

    def handle_add(self, **_):  # type: ignore[no-untyped-def]
        return ("/bill-templates", None)

    def handle_edit(self, **_):  # type: ignore[no-untyped-def]
        return ("/bill-templates", None)

    def handle_delete(self, **_):  # type: ignore[no-untyped-def]
        return "/bill-templates"

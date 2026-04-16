"""Page-service layer for the master-data list pages.

One service handles all five list pages (Accounts / Owners / Lots /
Vendors / Bank Accounts) because they share the same template and
differ only in which repository method supplies the rows and which
view-model builder shapes the columns.

Kept separate from ``ui_server.py`` so the report-console service and
the list-page service are independently readable — they have nothing
functionally to share.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from http import HTTPStatus

from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.repositories.lots_repo import LotsRepository
from hoa_accounting.repositories.owners_repo import OwnersRepository
from hoa_accounting.repositories.vendors_repo import VendorsRepository
from hoa_accounting.web.master_data_view_models import (
    build_accounts_list_context,
    build_bank_accounts_list_context,
    build_lots_list_context,
    build_owners_list_context,
    build_vendors_list_context,
)
from hoa_accounting.web.template_engine import render_template


@dataclass(frozen=True)
class ListPageResponse:
    """Simple UI response for a list page render."""

    status_code: int
    body_html: str


class MasterDataListService:
    """Render any one of the master-data list pages from a connection."""

    TEMPLATE = "master_data_list.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def render_accounts(
        self, *, org: dict[str, object] | None = None, theme: str = "warm"
    ) -> ListPageResponse:
        rows = AccountsRepository(self.conn).list_chart()
        ctx = build_accounts_list_context(rows=rows, org=org, theme=theme)
        return self._render(ctx)

    def render_owners(
        self, *, org: dict[str, object] | None = None, theme: str = "warm"
    ) -> ListPageResponse:
        rows = OwnersRepository(self.conn).list_owners()
        ctx = build_owners_list_context(rows=rows, org=org, theme=theme)
        return self._render(ctx)

    def render_lots(
        self, *, org: dict[str, object] | None = None, theme: str = "warm"
    ) -> ListPageResponse:
        rows = LotsRepository(self.conn).list_lots()
        ctx = build_lots_list_context(rows=rows, org=org, theme=theme)
        return self._render(ctx)

    def render_vendors(
        self, *, org: dict[str, object] | None = None, theme: str = "warm"
    ) -> ListPageResponse:
        rows = VendorsRepository(self.conn).list_vendors()
        ctx = build_vendors_list_context(rows=rows, org=org, theme=theme)
        return self._render(ctx)

    def render_bank_accounts(
        self, *, org: dict[str, object] | None = None, theme: str = "warm"
    ) -> ListPageResponse:
        rows = BankAccountsRepository(self.conn).list_bank_accounts()
        ctx = build_bank_accounts_list_context(rows=rows, org=org, theme=theme)
        return self._render(ctx)

    def _render(self, ctx) -> ListPageResponse:
        body = render_template(self.TEMPLATE, asdict(ctx))
        return ListPageResponse(status_code=HTTPStatus.OK, body_html=body)

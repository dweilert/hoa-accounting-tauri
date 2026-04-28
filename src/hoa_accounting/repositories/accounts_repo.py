"""Stub: Chart of Accounts has been retired. This shim keeps imports working
while callers are migrated. All methods return safe defaults — pages that
actually depend on chart-of-accounts data will degrade visibly but not crash
at boot time."""

from __future__ import annotations

import sqlite3


class AccountsRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get_by_number(self, account_number: str):  # noqa: ARG002
        return None

    def get_by_id(self, account_id: int):  # noqa: ARG002
        return None

    def list_chart(self):
        return []

    def list_accounts_by_type(self, account_type_code: str = ""):  # noqa: ARG002
        return []

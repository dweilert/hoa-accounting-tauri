"""Stub: Year-End Close has been retired."""

from __future__ import annotations


class YearEndCloseRepository:
    def __init__(self, conn=None) -> None:  # noqa: ARG002
        pass

    def is_year_closed(self, fiscal_year: int) -> bool:  # noqa: ARG002
        return False

    def list_closes(self):
        return []

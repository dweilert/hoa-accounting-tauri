"""Shared ``PageResponse`` dataclass for the ``*Pages`` request layer.

Single source of truth for the simple ``(status_code, body_html)`` envelope
returned by page-render methods. Previously duplicated in
``bank_statement_pages`` and ``bank_transactions_pages`` — kept identical
by convention, which is exactly the kind of thing that drifts.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str

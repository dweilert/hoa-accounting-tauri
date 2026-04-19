"""Global search — LIKE queries across owners, lots, vendors, journal entries,
payments, and assessments. Results grouped by category, max 8 per group."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from http import HTTPStatus

from hoa_accounting.web.template_engine import render_template

MAX_PER_GROUP = 8


@dataclass
class SearchHit:
    title: str
    subtitle: str
    url: str
    badge: str = ""


@dataclass
class SearchGroup:
    label: str
    hits: list[SearchHit] = field(default_factory=list)
    total: int = 0

    @property
    def has_more(self) -> bool:
        return self.total > len(self.hits)


@dataclass
class SearchPageResponse:
    status_code: int
    body_html: str


class SearchPages:
    TEMPLATE = "search_results.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def render(self, *, q: str, org: dict, theme: str) -> SearchPageResponse:
        q = (q or "").strip()
        groups: list[SearchGroup] = []

        if q:
            term = f"%{q}%"
            groups = [
                self._search_owners(term),
                self._search_lots(term),
                self._search_vendors(term),
                self._search_journal_entries(term),
                self._search_payments(term),
                self._search_assessments(term),
            ]

        html = render_template(self.TEMPLATE, {
            "org": org,
            "theme": theme,
            "page_key": "search",
            "active_nav": "",
            "search_q": q,
            "q": q,
            "groups": groups,
            "total_hits": sum(g.total for g in groups),
        })
        return SearchPageResponse(status_code=HTTPStatus.OK, body_html=html)

    # ── Category queries ───────────────────────────────────────────────

    def _search_owners(self, term: str) -> SearchGroup:
        rows = self._conn.execute(
            """
            SELECT id,
                   TRIM(COALESCE(first_name,'') || ' ' || COALESCE(last_name,'')) AS full_name,
                   email, phone
            FROM owners
            WHERE active_flag = 1
              AND (first_name || ' ' || last_name LIKE ?
                   OR email LIKE ?
                   OR phone LIKE ?)
            ORDER BY last_name, first_name
            LIMIT ?
            """,
            (term, term, term, MAX_PER_GROUP + 1),
        ).fetchall()
        count_row = self._conn.execute(
            """
            SELECT COUNT(*) FROM owners
            WHERE active_flag = 1
              AND (first_name || ' ' || last_name LIKE ?
                   OR email LIKE ? OR phone LIKE ?)
            """,
            (term, term, term),
        ).fetchone()
        hits = [
            SearchHit(
                title=r["full_name"] or "(no name)",
                subtitle=r["email"] or r["phone"] or "",
                url=f"/owners/{r['id']}/edit",
            )
            for r in rows[:MAX_PER_GROUP]
        ]
        return SearchGroup(label="Owners", hits=hits, total=count_row[0])

    def _search_lots(self, term: str) -> SearchGroup:
        rows = self._conn.execute(
            """
            SELECT l.id, l.lot_number,
                   l.street_address_1, l.city, l.state,
                   GROUP_CONCAT(
                     TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,'')),
                     ', '
                   ) AS owners
            FROM lots l
            LEFT JOIN lot_ownership lo ON lo.lot_id = l.id AND lo.end_date IS NULL
            LEFT JOIN owners o ON o.id = lo.owner_id
            WHERE l.active_flag = 1
              AND (l.lot_number LIKE ?
                   OR l.street_address_1 LIKE ?
                   OR l.city LIKE ?
                   OR l.postal_code LIKE ?)
            GROUP BY l.id
            ORDER BY l.lot_number
            LIMIT ?
            """,
            (term, term, term, term, MAX_PER_GROUP + 1),
        ).fetchall()
        count_row = self._conn.execute(
            """
            SELECT COUNT(*) FROM lots
            WHERE active_flag = 1
              AND (lot_number LIKE ? OR street_address_1 LIKE ?
                   OR city LIKE ? OR postal_code LIKE ?)
            """,
            (term, term, term, term),
        ).fetchone()
        hits = [
            SearchHit(
                title=f"Lot {r['lot_number']}",
                subtitle=" · ".join(filter(None, [
                    r["street_address_1"],
                    r["owners"],
                ])),
                url=f"/lots/{r['id']}/edit",
            )
            for r in rows[:MAX_PER_GROUP]
        ]
        return SearchGroup(label="Lots", hits=hits, total=count_row[0])

    def _search_vendors(self, term: str) -> SearchGroup:
        rows = self._conn.execute(
            """
            SELECT id, vendor_name, contact_name, email, phone
            FROM vendors
            WHERE active_flag = 1
              AND (vendor_name LIKE ? OR contact_name LIKE ?
                   OR email LIKE ? OR phone LIKE ?)
            ORDER BY vendor_name COLLATE NOCASE
            LIMIT ?
            """,
            (term, term, term, term, MAX_PER_GROUP + 1),
        ).fetchall()
        count_row = self._conn.execute(
            """
            SELECT COUNT(*) FROM vendors
            WHERE active_flag = 1
              AND (vendor_name LIKE ? OR contact_name LIKE ?
                   OR email LIKE ? OR phone LIKE ?)
            """,
            (term, term, term, term),
        ).fetchone()
        hits = [
            SearchHit(
                title=r["vendor_name"],
                subtitle=" · ".join(filter(None, [r["contact_name"], r["email"]])),
                url=f"/vendors/{r['id']}/edit",
            )
            for r in rows[:MAX_PER_GROUP]
        ]
        return SearchGroup(label="Vendors", hits=hits, total=count_row[0])

    def _search_journal_entries(self, term: str) -> SearchGroup:
        rows = self._conn.execute(
            """
            SELECT id, entry_number, entry_date, memo, status, source_type
            FROM journal_entries
            WHERE (entry_number LIKE ? OR memo LIKE ?)
            ORDER BY entry_date DESC, id DESC
            LIMIT ?
            """,
            (term, term, MAX_PER_GROUP + 1),
        ).fetchall()
        count_row = self._conn.execute(
            "SELECT COUNT(*) FROM journal_entries WHERE entry_number LIKE ? OR memo LIKE ?",
            (term, term),
        ).fetchone()
        hits = [
            SearchHit(
                title=f"JE-{r['entry_number']}",
                subtitle=" · ".join(filter(None, [r["entry_date"], r["memo"]])),
                url=f"/journal-entries/{r['id']}",
                badge=r["status"] or "",
            )
            for r in rows[:MAX_PER_GROUP]
        ]
        return SearchGroup(label="Journal Entries", hits=hits, total=count_row[0])

    def _search_payments(self, term: str) -> SearchGroup:
        rows = self._conn.execute(
            """
            SELECT p.id, p.payment_date, p.amount,
                   p.receipt_number, p.reference_number,
                   TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,'')) AS owner_name
            FROM payments p
            LEFT JOIN owners o ON o.id = p.owner_id
            WHERE (p.receipt_number LIKE ? OR p.reference_number LIKE ?
                   OR p.notes LIKE ?
                   OR (o.first_name || ' ' || o.last_name) LIKE ?)
            ORDER BY p.payment_date DESC, p.id DESC
            LIMIT ?
            """,
            (term, term, term, term, MAX_PER_GROUP + 1),
        ).fetchall()
        count_row = self._conn.execute(
            """
            SELECT COUNT(*) FROM payments p
            LEFT JOIN owners o ON o.id = p.owner_id
            WHERE (p.receipt_number LIKE ? OR p.reference_number LIKE ?
                   OR p.notes LIKE ?
                   OR (o.first_name || ' ' || o.last_name) LIKE ?)
            """,
            (term, term, term, term),
        ).fetchone()
        hits = [
            SearchHit(
                title=f"Payment ${r['amount']:,.2f} — {r['owner_name'] or 'Unknown'}",
                subtitle=" · ".join(filter(None, [
                    r["payment_date"],
                    f"Receipt {r['receipt_number']}" if r["receipt_number"] else "",
                    f"Ref {r['reference_number']}" if r["reference_number"] else "",
                ])),
                url="/deposits",
            )
            for r in rows[:MAX_PER_GROUP]
        ]
        return SearchGroup(label="Payments", hits=hits, total=count_row[0])

    def _search_assessments(self, term: str) -> SearchGroup:
        rows = self._conn.execute(
            """
            SELECT a.id, a.assessment_date, a.amount, a.charge_type,
                   a.status, a.description,
                   TRIM(COALESCE(o.first_name,'') || ' ' || COALESCE(o.last_name,'')) AS owner_name,
                   l.lot_number
            FROM assessments a
            LEFT JOIN owners o ON o.id = a.owner_id
            LEFT JOIN lots l ON l.id = a.lot_id
            WHERE (a.description LIKE ? OR a.charge_type LIKE ?
                   OR (o.first_name || ' ' || o.last_name) LIKE ?
                   OR l.lot_number LIKE ?)
            ORDER BY a.assessment_date DESC, a.id DESC
            LIMIT ?
            """,
            (term, term, term, term, MAX_PER_GROUP + 1),
        ).fetchall()
        count_row = self._conn.execute(
            """
            SELECT COUNT(*) FROM assessments a
            LEFT JOIN owners o ON o.id = a.owner_id
            LEFT JOIN lots l ON l.id = a.lot_id
            WHERE (a.description LIKE ? OR a.charge_type LIKE ?
                   OR (o.first_name || ' ' || o.last_name) LIKE ?
                   OR l.lot_number LIKE ?)
            """,
            (term, term, term, term),
        ).fetchone()
        hits = [
            SearchHit(
                title=f"${r['amount']:,.2f} — {r['description'] or r['charge_type']}",
                subtitle=" · ".join(filter(None, [
                    r["assessment_date"],
                    f"Lot {r['lot_number']}" if r["lot_number"] else "",
                    r["owner_name"],
                ])),
                url="/assessments/bill",
                badge=r["status"] or "",
            )
            for r in rows[:MAX_PER_GROUP]
        ]
        return SearchGroup(label="Assessments", hits=hits, total=count_row[0])

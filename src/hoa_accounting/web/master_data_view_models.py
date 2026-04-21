"""View-model builders for the master-data list pages.

Each page has a common shape: title, description, list of column
definitions (label / key / alignment), and a list of row dicts. The Flask
view just hands a ready-to-render context to the generic list template.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass



@dataclass(frozen=True)
class ListColumnVM:
    """One column on a master-data list table."""

    key: str
    label: str
    numeric: bool = False
    mono: bool = False  # render monospace (for account numbers, codes)


@dataclass(frozen=True)
class ListPageContext:
    """Template context for any master-data list page."""

    page_key: str           # e.g. "accounts", "owners" — for breadcrumb/active
    heading: str            # "Chart of Accounts"
    description: str        # short paragraph above the table
    columns: list[ListColumnVM]
    rows: list[dict[str, object]]
    empty_message: str
    org: dict[str, object]
    active_nav: str         # "master-data"
    breadcrumb: str         # "Master Data"
    theme: str


def _format_address(row: sqlite3.Row, *, a1: str, a2: str | None, city: str,
                    state: str, postal: str) -> str:
    """Flatten a scattered address-column row into one human string."""
    parts: list[str] = []
    if row[a1]:
        parts.append(str(row[a1]))
    if a2 and row[a2]:
        parts.append(str(row[a2]))
    tail_bits: list[str] = []
    if row[city]:
        tail_bits.append(str(row[city]))
    if row[state]:
        tail_bits.append(str(row[state]))
    if row[postal]:
        tail_bits.append(str(row[postal]))
    if tail_bits:
        parts.append(", ".join(tail_bits))
    return " · ".join(parts)


def _active_cell(flag: object) -> str:
    return "Active" if int(flag or 0) == 1 else "Inactive"


# ── Page-specific row builders ────────────────────────────────────────


def build_accounts_list_context(
    *,
    rows: list[sqlite3.Row],
    org: dict[str, object] | None,
    theme: str,
) -> ListPageContext:
    cols = [
        ListColumnVM(key="account_number", label="Number", mono=True),
        ListColumnVM(key="account_name", label="Account"),
        ListColumnVM(key="account_type_name", label="Type"),
        ListColumnVM(key="fund_code", label="Fund"),
        ListColumnVM(key="group_code", label="Group"),
        ListColumnVM(key="is_bank_account_label", label="Bank"),
    ]
    vm_rows: list[dict[str, object]] = []
    for r in rows:
        vm_rows.append({
            "account_number": r["account_number"],
            "account_name": r["account_name"],
            "account_type_name": r["account_type_name"],
            "fund_code": r["fund_code"],
            "group_code": r["group_code"] or "",
            "is_bank_account_label": "✓" if int(r["is_bank_account"] or 0) == 1 else "",
        })
    return ListPageContext(
        page_key="accounts",
        heading="Chart of Accounts",
        description=(
            "All accounts used by the system — bank, receivable, equity, and fund balance. "
            "Expense accounts show their HOA spending group; balance-sheet and "
            "income accounts leave the Group column blank."
        ),
        columns=cols,
        rows=vm_rows,
        empty_message="No active accounts. Run the initializer to seed a starter chart.",
        org=org or {},
        active_nav="master-data",
        breadcrumb="Master Data",
        theme=theme,
    )


def build_owners_list_context(
    *,
    rows: list[sqlite3.Row],
    org: dict[str, object] | None,
    theme: str,
) -> ListPageContext:
    cols = [
        ListColumnVM(key="display_name", label="Owner"),
        ListColumnVM(key="owner_type", label="Type"),
        ListColumnVM(key="email", label="Email"),
        ListColumnVM(key="phone", label="Phone"),
        ListColumnVM(key="address", label="Address"),
    ]
    vm_rows: list[dict[str, object]] = []
    for r in rows:
        vm_rows.append({
            "display_name": r["display_name"],
            "owner_type": r["owner_type"],
            "email": r["email"] or "",
            "phone": r["phone"] or "",
            "address": _format_address(
                r, a1="city", a2=None, city="city", state="state", postal="postal_code"
            ),
        })
    return ListPageContext(
        page_key="owners",
        heading="Owners",
        description=(
            "People and entities that own lots in the association. The "
            "current primary contact for each lot appears on the Lots page."
        ),
        columns=cols,
        rows=vm_rows,
        empty_message="No owners on record.",
        org=org or {},
        active_nav="master-data",
        breadcrumb="Master Data",
        theme=theme,
    )


def build_lots_list_context(
    *,
    rows: list[sqlite3.Row],
    org: dict[str, object] | None,
    theme: str,
) -> ListPageContext:
    cols = [
        ListColumnVM(key="lot_number", label="Lot #", mono=True),
        ListColumnVM(key="street", label="Street Address"),
        ListColumnVM(key="owner_names", label="Owner(s)"),
        ListColumnVM(key="occupancy", label="Occupancy"),
        ListColumnVM(key="status", label="Status"),
    ]
    vm_rows: list[dict[str, object]] = []
    for r in rows:
        street_parts = [r["street_address_1"] or "", r["street_address_2"] or ""]
        street = " ".join(p for p in street_parts if p).strip()
        occupancy = (
            "Owner Occupied" if r["is_owner_occupied"]
            else f"Renter: {r['renter_name'] or '—'}"
        )
        vm_rows.append({
            "lot_number": r["lot_number"],
            "street": street,
            "owner_names": r["owner_names"] or "—",
            "occupancy": occupancy,
            "status": _active_cell(r["active_flag"]),
        })
    return ListPageContext(
        page_key="lots",
        heading="Lots",
        description=(
            "Every lot in the association, with its current primary-contact "
            "owner and occupancy status."
        ),
        columns=cols,
        rows=vm_rows,
        empty_message="No lots on record.",
        org=org or {},
        active_nav="master-data",
        breadcrumb="Master Data",
        theme=theme,
    )


def build_vendors_list_context(
    *,
    rows: list[sqlite3.Row],
    org: dict[str, object] | None,
    theme: str,
) -> ListPageContext:
    cols = [
        ListColumnVM(key="vendor_name", label="Vendor"),
        ListColumnVM(key="contact_name", label="Contact"),
        ListColumnVM(key="email", label="Email"),
        ListColumnVM(key="phone", label="Phone"),
        ListColumnVM(key="city_state", label="City / State"),
    ]
    vm_rows: list[dict[str, object]] = []
    for r in rows:
        city_state = ", ".join(
            p for p in [r["city"] or "", r["state"] or ""] if p
        )
        vm_rows.append({
            "vendor_name": r["vendor_name"],
            "contact_name": r["contact_name"] or "",
            "email": r["email"] or "",
            "phone": r["phone"] or "",
            "city_state": city_state,
        })
    return ListPageContext(
        page_key="vendors",
        heading="Vendors",
        description=(
            "Companies and service providers the HOA pays. Used when "
            "entering vendor bills and bill payments."
        ),
        columns=cols,
        rows=vm_rows,
        empty_message="No vendors on record.",
        org=org or {},
        active_nav="master-data",
        breadcrumb="Master Data",
        theme=theme,
    )


def build_bank_accounts_list_context(
    *,
    rows: list[sqlite3.Row],
    org: dict[str, object] | None,
    theme: str,
) -> ListPageContext:
    cols = [
        ListColumnVM(key="account_name", label="Bank Account"),
        ListColumnVM(key="institution_name", label="Institution"),
        ListColumnVM(key="account_type", label="Type"),
        ListColumnVM(key="last4", label="Last 4", mono=True),
        ListColumnVM(key="gl", label="Linked Account"),
        ListColumnVM(key="fund", label="Fund"),
    ]
    vm_rows: list[dict[str, object]] = []
    for r in rows:
        vm_rows.append({
            "account_name": r["account_name"],
            "institution_name": r["institution_name"],
            "account_type": r["account_type"],
            "last4": r["account_last4"] or "",
            "gl": f"{r['gl_account_number']} · {r['gl_account_name']}",
            "fund": r["gl_fund_code"],
        })
    return ListPageContext(
        page_key="bank-accounts",
        heading="Bank Accounts",
        description=(
            "Physical bank accounts and the GL cash account each one "
            "posts to. Used when recording owner payments and vendor "
            "bill payments."
        ),
        columns=cols,
        rows=vm_rows,
        empty_message="No bank accounts on record.",
        org=org or {},
        active_nav="master-data",
        breadcrumb="Master Data",
        theme=theme,
    )

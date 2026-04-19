"""GL Transaction Import — System › GL Import.

Handles the MMPOA 2026GL.csv format with four record types:

  OwnerBill → DUES assessment via AssessmentService
  OwnerPay  → dues payment via PaymentService (auto-applies to open assessments)
  Exp       → vendor bill + immediate payment via VendorBill/VendorPaymentService
  Income    → non-dues income, OR RESALE_FEE for "Title Xfer" (lot 4207)

Three-step flow:
  GET  /admin/gl-import          — upload form
  POST /admin/gl-import/preview  — parse CSV, show preview table
  POST /admin/gl-import/run      — execute transactions, show results
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from http import HTTPStatus

from hoa_accounting.repositories.accounts_repo import AccountsRepository
from hoa_accounting.repositories.assessments_repo import AssessmentsRepository
from hoa_accounting.repositories.bank_accounts_repo import BankAccountsRepository
from hoa_accounting.services.factory import ServiceFactory
from hoa_accounting.services.non_dues_income_service import IncomeRow
from hoa_accounting.web.template_engine import render_template

# ── GL account constants ──────────────────────────────────────────────────────

AR_ACCOUNT    = "1100"   # Accounts Receivable — Owners
AP_ACCOUNT    = "2000"   # Accounts Payable
DUES_INCOME   = "4000"   # Assessment Income
RESALE_INCOME = "4070"   # Resale Certificate Fee Income
INT_INCOME    = "4200"   # Interest Income (bank interest)

# The "Title Xfer" income row in the CSV is a resale fee for this lot.
TITLE_XFER_LOT = "4207"

# Expense Group/Category (both lowercased) → GL account number
EXPENSE_MAP: dict[tuple[str, str], str] = {
    ("entrance",  "gate"):             "6501",
    ("sewer",     "sewer"):            "6201",
    ("utilities", "utilities"):        "6601",
    ("landscape", "mow & blow"):       "6101",
    ("landscape", "mulch"):            "6104",
    ("landscape", "bed maintenance"):  "6106",
    ("misc",      "misc"):             "6801",
}

# ── Parsing helpers ───────────────────────────────────────────────────────────

def _parse_amount(s: str) -> Decimal:
    clean = re.sub(r"[$,\s]", "", s.strip())
    try:
        return Decimal(clean) if clean else Decimal("0")
    except InvalidOperation:
        return Decimal("0")


def _parse_date(s: str) -> str | None:
    """Accept M/D/YY or M/D/YYYY → YYYY-MM-DD."""
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", s.strip())
    if not m:
        return None
    mo, da, yr = m.group(1), m.group(2), m.group(3)
    if len(yr) == 2:
        yr = "20" + yr
    try:
        return datetime(int(yr), int(mo), int(da)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _month_end(yyyy_mm_dd: str) -> str:
    import calendar
    y, m = int(yyyy_mm_dd[:4]), int(yyyy_mm_dd[5:7])
    return f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def _next_day(yyyy_mm_dd: str) -> str:
    d = datetime.strptime(yyyy_mm_dd, "%Y-%m-%d")
    return (d + timedelta(days=1)).strftime("%Y-%m-%d")


def _clean_name(name: str) -> str:
    """Strip trailing parenthetical like '(Renter)' and whitespace."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class GlRow:
    record_type:   str
    house_year:    str
    name:          str
    payments:      Decimal
    billings:      Decimal
    billing_month: str
    check_info:    str
    exp_group:     str
    exp_category:  str
    comment:       str
    date_str:      str   # YYYY-MM-DD
    raw_row_num:   int


@dataclass
class OwnershipChange:
    lot_number:     str
    lot_id:         int
    prior_name:     str
    prior_end_date: str   # last day of prior owner's last billing month
    new_name:       str


@dataclass
class PreviewRow:
    row_num:  int
    action:   str
    lot:      str
    party:    str
    amount:   Decimal
    date:     str
    notes:    str
    status:   str   # ok | warning | error | skip


@dataclass(frozen=True)
class GlImportResponse:
    status_code: int
    body_html:   str


# ── Page handler ──────────────────────────────────────────────────────────────

class GlImportPages:
    UPLOAD_TEMPLATE  = "gl_import.html"
    PREVIEW_TEMPLATE = "gl_import_preview.html"
    RESULT_TEMPLATE  = "gl_import_result.html"

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn    = conn
        self.factory = ServiceFactory(conn)
        self._acct_cache: dict[str, int] = {}

    # ── GET /admin/gl-import ──────────────────────────────────────────────────

    def render_page(self, *, org: dict, theme: str, error: str = "") -> GlImportResponse:
        ctx = {
            "heading": "GL Transaction Import", "breadcrumb": "System",
            "org": org, "theme": theme, "page_key": "gl-import",
            "error_message": error,
        }
        return GlImportResponse(HTTPStatus.OK, render_template(self.UPLOAD_TEMPLATE, ctx))

    # ── POST /admin/gl-import/preview ─────────────────────────────────────────

    def handle_preview(
        self, *, csv_content: str, org: dict, theme: str
    ) -> GlImportResponse:
        rows = self._parse_csv(csv_content)
        if not rows:
            return self.render_page(org=org, theme=theme,
                                    error="No valid data rows found in CSV.")

        ownership = self._detect_ownership_changes(rows)
        preview   = self._build_preview(rows, ownership)

        ok    = sum(1 for p in preview if p.status == "ok")
        warn  = sum(1 for p in preview if p.status == "warning")
        err   = sum(1 for p in preview if p.status == "error")
        skip  = sum(1 for p in preview if p.status == "skip")

        ctx = {
            "heading": "GL Import Preview", "breadcrumb": "System",
            "org": org, "theme": theme, "page_key": "gl-import",
            "preview": preview, "ownership": ownership,
            "ok": ok, "warn": warn, "err": err, "skip": skip,
            "csv_content": csv_content,
            "has_errors": err > 0,
        }
        return GlImportResponse(HTTPStatus.OK,
                                render_template(self.PREVIEW_TEMPLATE, ctx))

    # ── POST /admin/gl-import/run ─────────────────────────────────────────────

    def handle_run(
        self, *, csv_content: str, org: dict, theme: str
    ) -> GlImportResponse:
        rows      = self._parse_csv(csv_content)
        ownership = self._detect_ownership_changes(rows)
        results: list[dict] = []
        errors:  list[dict] = []

        # Shared lookups
        try:
            ar_id    = self._acct_id(AR_ACCOUNT)
            ap_id    = self._acct_id(AP_ACCOUNT)
            dues_id  = self._acct_id(DUES_INCOME)
            res_id   = self._acct_id(RESALE_INCOME)
            int_id   = self._acct_id(INT_INCOME)
        except RuntimeError as exc:
            return self._render_result([], [{"action": "Setup", "error": str(exc)}], org, theme)

        bank_rows = BankAccountsRepository(self.conn).list_bank_accounts()
        bank = next((b for b in bank_rows if b["active_flag"]), None)
        if bank is None:
            return self._render_result([], [{"action": "Setup", "error": "No active bank account."}], org, theme)
        bank_id = int(bank["id"])
        cash_gl = int(bank["gl_account_id"])

        # ── Step 1: Ownership setup ───────────────────────────────────────────
        for oc in ownership:
            for e in self._setup_ownership(oc):
                errors.append({"action": f"Ownership {oc.lot_number}", "error": e})

        # ── Step 2: Dues bills (all months, deduped by lot+month) ────────────
        seen_bills: set[tuple] = set()
        for r in sorted((x for x in rows if x.record_type == "OwnerBill"),
                        key=lambda x: x.date_str):
            key = (r.house_year, r.billing_month.strip().lower())
            if key in seen_bills:
                results.append({"action": f"Bill {r.house_year}/{r.billing_month}",
                                 "status": "skip", "note": "Duplicate"})
                continue
            seen_bills.add(key)
            err = self._post_bill(r, ar_id=ar_id, income_id=dues_id)
            if err:
                errors.append({"action": f"Bill {r.house_year}/{r.billing_month}", "error": err})
            else:
                results.append({"action": f"Dues bill · Lot {r.house_year} · {r.billing_month} · ${r.billings:.2f}", "status": "ok"})

        # ── Step 3: Dues payments (deduped by lot+check+amount) ──────────────
        seen_pays: set[tuple] = set()
        for r in sorted((x for x in rows if x.record_type == "OwnerPay"),
                        key=lambda x: x.date_str):
            chk = r.check_info.strip()
            key = (r.house_year, chk, str(r.payments))
            if key in seen_pays:
                results.append({"action": f"Pay {r.house_year} chk={chk}",
                                 "status": "skip", "note": "Duplicate"})
                continue
            seen_pays.add(key)
            err = self._post_payment(r, ar_id=ar_id, cash_id=cash_gl, bank_id=bank_id)
            if err:
                errors.append({"action": f"Pay Lot {r.house_year} ${r.payments:.2f}", "error": err})
            else:
                results.append({"action": f"Dues payment · Lot {r.house_year} · ${r.payments:.2f} · chk {chk}", "status": "ok"})

        # ── Step 4: Expenses ─────────────────────────────────────────────────
        for r in sorted((x for x in rows if x.record_type == "Exp"),
                        key=lambda x: x.date_str):
            err = self._post_expense(r, ap_id=ap_id, bank_id=bank_id, cash_id=cash_gl)
            if err:
                errors.append({"action": f"Expense {r.name}", "error": err})
            else:
                results.append({"action": f"Expense · {r.name} · ${r.payments:.2f}", "status": "ok"})

        # ── Step 5: Income entries ───────────────────────────────────────────
        for r in sorted((x for x in rows if x.record_type == "Income"),
                        key=lambda x: x.date_str):
            if r.name.strip().lower() == "title xfer":
                err = self._post_resale_fee(
                    r, lot_number=TITLE_XFER_LOT,
                    ar_id=ar_id, resale_income_id=res_id,
                    cash_id=cash_gl, bank_id=bank_id,
                )
            else:
                err = self._post_non_dues_income(r, bank_id=bank_id, income_id=int_id)
            if err:
                errors.append({"action": f"Income {r.name}", "error": err})
            else:
                results.append({"action": f"Income · {r.name} · ${r.payments:.2f}", "status": "ok"})

        if results:
            self.conn.commit()

        return self._render_result(results, errors, org, theme)

    # ── CSV parsing ───────────────────────────────────────────────────────────

    def _parse_csv(self, content: str) -> list[GlRow]:
        reader = csv.reader(io.StringIO(content.strip()))
        all_rows = list(reader)
        if len(all_rows) < 2:
            return []
        headers = [h.strip() for h in all_rows[0]]
        result: list[GlRow] = []
        for i, row in enumerate(all_rows[1:], start=2):
            if not any(c.strip() for c in row):
                continue
            d = {headers[j]: (row[j].strip() if j < len(row) else "")
                 for j in range(len(headers))}
            rt = d.get("Record Type", "").strip()
            if rt not in ("OwnerBill", "OwnerPay", "Exp", "Income"):
                continue
            date_str = _parse_date(d.get("Date of Transaction", ""))
            if not date_str:
                continue
            result.append(GlRow(
                record_type   = rt,
                house_year    = d.get("House # / Year", "").strip(),
                name          = d.get("Name", "").strip(),
                payments      = _parse_amount(d.get("Payments", "")),
                billings      = _parse_amount(d.get("Billings", "")),
                billing_month = d.get("Billing Month", "").strip(),
                check_info    = d.get("Check # / Info", "").strip(),
                exp_group     = d.get("Expense Group", "").strip().lower(),
                exp_category  = d.get("Expense Category", "").strip().lower(),
                comment       = d.get("Comment", "").strip(),
                date_str      = date_str,
                raw_row_num   = i,
            ))
        return result

    # ── Ownership change detection ────────────────────────────────────────────

    def _detect_ownership_changes(self, rows: list[GlRow]) -> list[OwnershipChange]:
        from collections import defaultdict
        lot_bills: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for r in rows:
            if r.record_type == "OwnerBill":
                lot_bills[r.house_year].append((r.date_str, r.name))

        changes: list[OwnershipChange] = []
        for lot_num, bill_list in sorted(lot_bills.items()):
            bill_list.sort()
            seen: list[tuple[str, str]] = []
            for dt, nm in bill_list:
                if not seen or seen[-1][1] != nm:
                    seen.append((dt, nm))
            if len(seen) < 2:
                continue

            prior_name = seen[0][1]
            new_name   = seen[-1][1]
            last_prior = max(dt for dt, nm in bill_list if nm == prior_name)
            prior_end  = _month_end(last_prior)

            lot_row = self.conn.execute(
                "SELECT id FROM lots WHERE lot_number=?", (lot_num,)
            ).fetchone()
            if lot_row is None:
                continue
            changes.append(OwnershipChange(
                lot_number=lot_num, lot_id=int(lot_row[0]),
                prior_name=prior_name, prior_end_date=prior_end,
                new_name=new_name,
            ))
        return changes

    # ── Preview builder ───────────────────────────────────────────────────────

    def _build_preview(
        self, rows: list[GlRow], ownership: list[OwnershipChange]
    ) -> list[PreviewRow]:
        preview: list[PreviewRow] = []
        seen_bills: set[tuple] = set()
        seen_pays:  set[tuple] = set()

        for r in rows:
            if r.record_type == "OwnerBill":
                key = (r.house_year, r.billing_month.lower())
                if key in seen_bills:
                    preview.append(PreviewRow(r.raw_row_num, "Post Dues Bill",
                        r.house_year, r.name, r.billings, r.date_str, "Duplicate — skip", "skip"))
                    continue
                seen_bills.add(key)
                lot = self.conn.execute(
                    "SELECT id FROM lots WHERE lot_number=?", (r.house_year,)
                ).fetchone()
                if not lot:
                    preview.append(PreviewRow(r.raw_row_num, "Post Dues Bill",
                        r.house_year, r.name, r.billings, r.date_str,
                        f"Lot {r.house_year} not found", "error"))
                    continue
                owner_id = self._find_owner_id(r.name)
                notes  = "" if owner_id else f"'{_clean_name(r.name)}' will be created as new owner"
                status = "ok" if owner_id else "warning"
                preview.append(PreviewRow(r.raw_row_num, "Post Dues Bill",
                    r.house_year, _clean_name(r.name), r.billings, r.date_str, notes, status))

            elif r.record_type == "OwnerPay":
                chk = r.check_info.strip()
                key = (r.house_year, chk, str(r.payments))
                if key in seen_pays:
                    preview.append(PreviewRow(r.raw_row_num, "Record Payment",
                        r.house_year, r.name, r.payments, r.date_str, "Duplicate — skip", "skip"))
                    continue
                seen_pays.add(key)
                lot = self.conn.execute(
                    "SELECT id FROM lots WHERE lot_number=?", (r.house_year,)
                ).fetchone()
                if not lot:
                    preview.append(PreviewRow(r.raw_row_num, "Record Payment",
                        r.house_year, r.name, r.payments, r.date_str,
                        f"Lot {r.house_year} not found", "error"))
                    continue
                owner_id = self._find_owner_id(r.name)
                notes  = f"chk {chk}" + ("" if owner_id else f" · '{_clean_name(r.name)}' will be created")
                status = "ok" if owner_id else "warning"
                preview.append(PreviewRow(r.raw_row_num, "Record Payment",
                    r.house_year, _clean_name(r.name), r.payments, r.date_str, notes, status))

            elif r.record_type == "Exp":
                vendor_id = self._find_vendor_id(r.name)
                acct_num  = EXPENSE_MAP.get((r.exp_group, r.exp_category))
                notes_parts: list[str] = []
                status = "ok"
                if not vendor_id:
                    notes_parts.append(f"'{r.name}' will be created as vendor")
                    status = "warning"
                if acct_num:
                    notes_parts.append(f"→ acct {acct_num}")
                else:
                    notes_parts.append(f"Unknown category {r.exp_group}/{r.exp_category}")
                    status = "error"
                preview.append(PreviewRow(r.raw_row_num, "Vendor Bill + Payment",
                    "—", r.name, r.payments, r.date_str, " · ".join(notes_parts), status))

            elif r.record_type == "Income":
                if r.name.strip().lower() == "title xfer":
                    preview.append(PreviewRow(r.raw_row_num, "Resale Fee + Payment",
                        TITLE_XFER_LOT, "Title company", r.payments, r.date_str,
                        f"RESALE_FEE assessment + payment for lot {TITLE_XFER_LOT} → acct {RESALE_INCOME}", "ok"))
                else:
                    preview.append(PreviewRow(r.raw_row_num, "Non-Dues Income",
                        "—", r.name, r.payments, r.date_str,
                        f"→ acct {INT_INCOME} (Interest Income)", "ok"))

        return preview

    # ── Ownership setup ───────────────────────────────────────────────────────

    def _setup_ownership(self, oc: OwnershipChange) -> list[str]:
        errors: list[str] = []

        # Prior owner — find or create, then set end_date on their lot_ownership
        prior_id = self._find_owner_id(oc.prior_name)
        if prior_id is None:
            prior_id = self._create_skeleton_owner(_clean_name(oc.prior_name), active=0)
            if prior_id is None:
                errors.append(f"Could not create prior owner '{_clean_name(oc.prior_name)}'")
                return errors

        lo = self.conn.execute(
            "SELECT id, end_date FROM lot_ownership WHERE lot_id=? AND owner_id=?",
            (oc.lot_id, prior_id),
        ).fetchone()
        if lo:
            if not lo["end_date"]:
                self.conn.execute(
                    "UPDATE lot_ownership SET end_date=? WHERE id=?",
                    (oc.prior_end_date, lo["id"]),
                )
        else:
            self.conn.execute(
                "INSERT INTO lot_ownership (lot_id, owner_id, start_date, end_date) VALUES (?,?,?,?)",
                (oc.lot_id, prior_id, "2026-01-01", oc.prior_end_date),
            )

        # New owner — find or create; add lot_ownership if none exists
        new_id = self._find_owner_id(oc.new_name)
        if new_id is None:
            new_id = self._create_skeleton_owner(_clean_name(oc.new_name), active=1)
            if new_id:
                new_start = _next_day(oc.prior_end_date)
                existing = self.conn.execute(
                    "SELECT id FROM lot_ownership WHERE lot_id=? AND owner_id=? AND end_date IS NULL",
                    (oc.lot_id, new_id),
                ).fetchone()
                if not existing:
                    self.conn.execute(
                        "INSERT INTO lot_ownership (lot_id, owner_id, start_date) VALUES (?,?,?)",
                        (oc.lot_id, new_id, new_start),
                    )

        return errors

    # ── Transaction posters ───────────────────────────────────────────────────

    def _post_bill(self, r: GlRow, *, ar_id: int, income_id: int) -> str | None:
        lot = self.conn.execute(
            "SELECT id FROM lots WHERE lot_number=?", (r.house_year,)
        ).fetchone()
        if not lot:
            return f"Lot {r.house_year} not found"

        owner_id = self._find_or_create_owner(r.name)
        if owner_id is None:
            return f"Could not find/create owner '{r.name}'"

        month_label = r.billing_month or r.date_str[:7]
        try:
            self.factory.assessment_service().post_assessment(
                entry_date=r.date_str,
                lot_id=int(lot[0]),
                owner_id=owner_id,
                amount=r.billings,
                description=f"Monthly dues — {month_label}",
                receivable_account_id=ar_id,
                income_account_id=income_id,
                charge_type="DUES",
                due_date=_month_end(r.date_str),
            )
        except Exception as exc:
            return str(exc)
        return None

    def _post_payment(
        self, r: GlRow, *, ar_id: int, cash_id: int, bank_id: int
    ) -> str | None:
        lot = self.conn.execute(
            "SELECT id FROM lots WHERE lot_number=?", (r.house_year,)
        ).fetchone()
        if not lot:
            return f"Lot {r.house_year} not found"

        owner_id = self._find_or_create_owner(r.name)
        if owner_id is None:
            return f"Could not find/create owner '{r.name}'"

        open_assessments = AssessmentsRepository(self.conn).list_open_for_owner(owner_id)
        apply_ids = [int(a["id"]) for a in open_assessments] or None

        chk     = r.check_info.strip() or None
        receipt = chk or f"IMP-{r.house_year}-{r.date_str}"
        desc    = f"Dues payment — {'check ' + chk if chk else r.date_str}"
        try:
            self.factory.payment_service().post_payment(
                entry_date=r.date_str,
                owner_id=owner_id,
                amount=r.payments,
                description=desc,
                cash_account_id=cash_id,
                receivable_account_id=ar_id,
                bank_account_id=bank_id,
                payment_method="CHECK",
                receipt_number=receipt,
                reference_number=chk,
                apply_to_assessment_ids=apply_ids,
            )
        except Exception as exc:
            return str(exc)
        return None

    def _post_expense(
        self, r: GlRow, *, ap_id: int, bank_id: int, cash_id: int
    ) -> str | None:
        vendor_id = self._find_or_create_vendor(r.name)
        if vendor_id is None:
            return f"Vendor '{r.name}' could not be created"

        acct_num = EXPENSE_MAP.get((r.exp_group, r.exp_category)) or next(
            (v for (g, _), v in EXPENSE_MAP.items() if g == r.exp_group), None
        )
        if not acct_num:
            return f"No GL account mapped for {r.exp_group}/{r.exp_category}"

        exp_id  = self._acct_id(acct_num)
        inv_num = f"GL2026-{r.raw_row_num:03d}"
        desc    = r.comment or f"{r.exp_group} — {r.exp_category}"
        try:
            result = self.factory.vendor_bill_service().post_vendor_bill(
                entry_date=r.date_str,
                vendor_id=vendor_id,
                amount=r.payments,
                description=desc,
                expense_account_id=exp_id,
                payable_account_id=ap_id,
                invoice_number=inv_num,
                invoice_date=r.date_str,
                due_date=r.date_str,
            )
        except Exception as exc:
            return str(exc)

        try:
            self.factory.vendor_payment_service().post_vendor_payment(
                entry_date=r.date_str,
                vendor_bill_id=result.vendor_bill_id,
                amount=r.payments,
                description=desc,
                payable_account_id=ap_id,
                cash_account_id=cash_id,
                bank_account_id=bank_id,
                check_number=r.check_info or None,
            )
        except Exception as exc:
            return str(exc)
        return None

    def _post_resale_fee(
        self, r: GlRow, *, lot_number: str,
        ar_id: int, resale_income_id: int, cash_id: int, bank_id: int,
    ) -> str | None:
        lot = self.conn.execute(
            "SELECT id FROM lots WHERE lot_number=?", (lot_number,)
        ).fetchone()
        if not lot:
            return f"Lot {lot_number} not found"
        lot_id = int(lot[0])

        # Find owner as of the transaction date (David Sandvig, end_date=Jan 31)
        owner = self.conn.execute(
            """SELECT o.id FROM lot_ownership lo
               JOIN owners o ON o.id = lo.owner_id
               WHERE lo.lot_id = ?
                 AND lo.start_date <= ?
                 AND (lo.end_date IS NULL OR lo.end_date >= ?)
               ORDER BY lo.start_date DESC LIMIT 1""",
            (lot_id, r.date_str, r.date_str),
        ).fetchone()
        if owner is None:
            owner = self.conn.execute(
                """SELECT o.id FROM lot_ownership lo JOIN owners o ON o.id=lo.owner_id
                   WHERE lo.lot_id=? AND lo.end_date IS NULL
                   ORDER BY lo.start_date ASC LIMIT 1""",
                (lot_id,),
            ).fetchone()
        if owner is None:
            return f"No owner found for lot {lot_number}"
        owner_id = int(owner[0])

        try:
            assess = self.factory.assessment_service().post_assessment(
                entry_date=r.date_str,
                lot_id=lot_id,
                owner_id=owner_id,
                amount=r.payments,
                description="Resale Certificate Fee",
                receivable_account_id=ar_id,
                income_account_id=resale_income_id,
                charge_type="RESALE_FEE",
                due_date=r.date_str,
            )
        except Exception as exc:
            return str(exc)

        try:
            self.factory.payment_service().post_payment(
                entry_date=r.date_str,
                owner_id=owner_id,
                amount=r.payments,
                description=f"Resale certificate fee — {r.comment or 'title company'}",
                cash_account_id=cash_id,
                receivable_account_id=ar_id,
                bank_account_id=bank_id,
                payment_method="CHECK",
                receipt_number=f"RESALE-{r.date_str}",
                reference_number=None,
                apply_to_assessment_ids=[assess.assessment_id],
            )
        except Exception as exc:
            return str(exc)
        return None

    def _post_non_dues_income(
        self, r: GlRow, *, bank_id: int, income_id: int
    ) -> str | None:
        source = r.name or r.comment or "Miscellaneous income"
        try:
            self.factory.non_dues_income_service().post_batch(
                posting_date=r.date_str,
                bank_account_id=bank_id,
                income_account_id=income_id,
                income_description=source,
                rows=[IncomeRow(amount=r.payments, other_source=source)],
            )
        except Exception as exc:
            return str(exc)
        return None

    # ── Lookup / create helpers ───────────────────────────────────────────────

    def _find_owner_id(self, csv_name: str) -> int | None:
        name  = _clean_name(csv_name)
        parts = name.split()
        if not parts:
            return None
        first = parts[0]
        last  = parts[-1] if len(parts) > 1 else ""

        # 1. Exact display_name match
        r = self.conn.execute(
            "SELECT id FROM owners WHERE LOWER(display_name)=LOWER(?)", (name,)
        ).fetchone()
        if r:
            return int(r[0])

        # 2. first_name + last_name match
        if last and last != first:
            r = self.conn.execute(
                "SELECT id FROM owners WHERE LOWER(first_name)=LOWER(?) AND LOWER(last_name)=LOWER(?)",
                (first, last),
            ).fetchone()
            if r:
                return int(r[0])

        # 3. display_name = first word only (e.g. display_name="Faiza" matches "Faiza Khan")
        r = self.conn.execute(
            "SELECT id FROM owners WHERE LOWER(display_name)=LOWER(?)", (first,)
        ).fetchone()
        if r:
            return int(r[0])

        return None

    def _find_or_create_owner(self, csv_name: str) -> int | None:
        oid = self._find_owner_id(csv_name)
        if oid:
            return oid
        name  = _clean_name(csv_name)
        parts = name.split()
        first = parts[0] if parts else name
        last  = parts[-1] if len(parts) > 1 else ""
        return self._create_skeleton_owner_raw(first, last, active=1)

    def _create_skeleton_owner(self, clean_name: str, *, active: int) -> int | None:
        parts = clean_name.split()
        first = parts[0] if parts else clean_name
        last  = parts[-1] if len(parts) > 1 else ""
        return self._create_skeleton_owner_raw(first, last, active=active)

    def _create_skeleton_owner_raw(
        self, first: str, last: str, *, active: int
    ) -> int | None:
        display = f"{first} {last}".strip() if last else first
        try:
            cur = self.conn.execute(
                """INSERT INTO owners
                   (owner_type, display_name, first_name, last_name, active_flag)
                   VALUES ('PERSON', ?, ?, ?, ?)""",
                (display, first, last or None, active),
            )
            return int(cur.lastrowid)
        except Exception:
            return None

    def _find_vendor_id(self, name: str) -> int | None:
        r = self.conn.execute(
            "SELECT id FROM vendors WHERE LOWER(vendor_name)=LOWER(?)", (name,)
        ).fetchone()
        return int(r[0]) if r else None

    def _find_or_create_vendor(self, name: str) -> int | None:
        vid = self._find_vendor_id(name)
        if vid:
            return vid
        try:
            cur = self.conn.execute(
                "INSERT INTO vendors (vendor_name, active_flag) VALUES (?, 1)", (name,)
            )
            return int(cur.lastrowid)
        except Exception:
            return None

    def _acct_id(self, number: str) -> int:
        if number not in self._acct_cache:
            row = AccountsRepository(self.conn).get_by_number(number)
            if row is None:
                raise RuntimeError(f"Account {number} not found in chart of accounts")
            self._acct_cache[number] = int(row["id"])
        return self._acct_cache[number]

    def _render_result(
        self, results: list, errors: list, org: dict, theme: str
    ) -> GlImportResponse:
        ctx = {
            "heading": "GL Import Results", "breadcrumb": "System",
            "org": org, "theme": theme, "page_key": "gl-import",
            "results": results, "errors": errors,
            "ok_count":    sum(1 for r in results if r.get("status") == "ok"),
            "skip_count":  sum(1 for r in results if r.get("status") == "skip"),
            "error_count": len(errors),
        }
        code = HTTPStatus.BAD_REQUEST if errors and not results else HTTPStatus.OK
        return GlImportResponse(code, render_template(self.RESULT_TEMPLATE, ctx))

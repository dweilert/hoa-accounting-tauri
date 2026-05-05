"""PDF renderers for the five publishable financial reports.

Each public function accepts the corresponding report DTO and returns
raw PDF bytes ready to upload to S3 or stream to the browser.

All five reports share the same visual language as ``owner_ledger_pdf``:
LETTER page, 0.65" margins, navy header row, alternating row fills,
and a navy grand-total footer row.
"""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from hoa_accounting.reporting.dto import (
    BudgetSummaryReport,
    ExpensesByDateReport,
    ExpenseVsBudgetReport,
    HomeownerContactListReport,
    YtdExpenseSummaryReport,
)

# ── Palette ───────────────────────────────────────────────────────────────────
_NAVY = colors.HexColor("#1e3a5f")
_BORDER = colors.HexColor("#d1d9e0")
_PANEL_BG = colors.HexColor("#f5f7fa")
_GROUP_BG = colors.HexColor("#dce3eb")
_OVER_BG = colors.HexColor("#fee2e2")
_UNDER_BG = colors.HexColor("#dcfce7")
_MUTED = colors.HexColor("#6b7280")

_PAGE_W, _PAGE_H = LETTER
_MARGIN = 0.65 * inch
_CW = _PAGE_W - 2 * _MARGIN  # usable content width ≈ 7.2"


# ── Shared helpers ────────────────────────────────────────────────────────────


def _doc(buf: io.BytesIO) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
    )


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "RptTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=_NAVY,
            spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "RptMeta",
            parent=base["Normal"],
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#555555"),
        ),
        "generated": ParagraphStyle(
            "RptGenerated",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=_MUTED,
        ),
    }


def _header_flowables(
    title: str,
    subtitle: str,
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    today = date.today().strftime("%B %d, %Y")
    return [
        Paragraph(title, styles["title"]),
        Paragraph(subtitle, styles["meta"]),
        Paragraph(f"Generated {today}", styles["generated"]),
        Spacer(1, 0.15 * inch),
    ]


def _money(d: Decimal) -> str:
    if d < 0:
        return f"(${abs(d):,.2f})"
    return f"${d:,.2f}"


def _base_style() -> list[tuple[Any, ...]]:
    """Base TableStyle commands shared by every table."""
    return [
        # Header row
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
        # Body rows
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _PANEL_BG]),
        # Grid / padding
        ("GRID", (0, 0), (-1, -1), 0.4, _BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]


def _build_table(
    data: list[list[str]],
    col_widths: list[float],
    extra_styles: list[tuple[Any, ...]],
    right_align_cols: list[int] | None = None,
) -> Table:
    """Build a Table with base + extra styles, optional right-aligned columns."""
    style_cmds = _base_style() + extra_styles
    if right_align_cols:
        for col in right_align_cols:
            style_cmds.append(("ALIGN", (col, 0), (col, -1), "RIGHT"))
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(style_cmds))
    return t


# ── 1. Expense vs Budget ──────────────────────────────────────────────────────


def render_expense_vs_budget_pdf(report: ExpenseVsBudgetReport) -> bytes:
    """Expense vs Budget — grouped by expense category group."""
    buf = io.BytesIO()
    styles = _styles()

    subtitle = (
        f"Fiscal Year {report.fiscal_year} · Fund: {report.fund_code} · "
        f"{report.from_date} to {report.to_date}"
    )
    flowables: list[Any] = _header_flowables("Expense vs Budget", subtitle, styles)

    # Column widths: Category | Budget | Actual | Variance | % Used  = 7.2"
    cw = [
        3.2 * inch,
        1.0 * inch,
        1.0 * inch,
        1.0 * inch,
        1.0 * inch,
    ]

    header = ["Category", "Budget", "Actual", "Variance", "% Used"]
    rows: list[list[str]] = [header]
    extras: list[tuple[Any, ...]] = []
    ri = 1  # current row index (0 = header)

    for group in report.groups:
        label = group.group_code or "General"

        # Group header
        rows.append([label, "", "", "", ""])
        extras += [
            ("BACKGROUND", (0, ri), (-1, ri), _GROUP_BG),
            ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
            ("SPAN", (0, ri), (-1, ri)),
        ]
        ri += 1

        for row in group.rows:
            pct = (
                f"{(row.actual_amount / row.budget_amount * 100):.0f}%"
                if row.budget_amount != Decimal("0.00")
                else "—"
            )
            rows.append(
                [
                    f"  {row.category_name}",
                    _money(row.budget_amount),
                    _money(row.actual_amount),
                    _money(row.variance),
                    pct,
                ]
            )
            # Highlight over-budget rows (variance < 0)
            if row.variance < Decimal("0.00"):
                extras.append(("BACKGROUND", (3, ri), (3, ri), _OVER_BG))
            ri += 1

        # Group subtotal
        g_pct = (
            f"{(group.group_actual / group.group_budget * 100):.0f}%"
            if group.group_budget != Decimal("0.00")
            else "—"
        )
        rows.append(
            [
                f"{label} Total",
                _money(group.group_budget),
                _money(group.group_actual),
                _money(group.group_variance),
                g_pct,
            ]
        )
        extras += [
            ("BACKGROUND", (0, ri), (-1, ri), _GROUP_BG),
            ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
        ]
        ri += 1

    # Grand total
    t_pct = (
        f"{(report.total_actual / report.total_budget * 100):.0f}%"
        if report.total_budget != Decimal("0.00")
        else "—"
    )
    rows.append(
        [
            "GRAND TOTAL",
            _money(report.total_budget),
            _money(report.total_actual),
            _money(report.total_variance),
            t_pct,
        ]
    )
    extras += [
        ("BACKGROUND", (0, ri), (-1, ri), _NAVY),
        ("TEXTCOLOR", (0, ri), (-1, ri), colors.white),
        ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
    ]

    flowables.append(_build_table(rows, cw, extras, right_align_cols=[1, 2, 3, 4]))

    doc = _doc(buf)
    doc.build(flowables)
    return buf.getvalue()


# ── 2. Expense Detail ─────────────────────────────────────────────────────────


def render_expense_detail_pdf(report: ExpensesByDateReport) -> bytes:
    """Expense Detail — chronological vendor bill lines."""
    buf = io.BytesIO()
    styles = _styles()

    subtitle = f"{report.from_date} to {report.to_date}"
    flowables: list[Any] = _header_flowables("Expense Detail", subtitle, styles)

    # Column widths: Date | Ref# | Account | Fund | Memo | Amount  = 7.2"
    cw = [
        0.70 * inch,
        0.80 * inch,
        1.50 * inch,
        0.50 * inch,
        2.70 * inch,
        1.00 * inch,
    ]

    header = ["Date", "Ref #", "Account", "Fund", "Memo", "Amount"]
    rows: list[list[str]] = [header]
    extras: list[tuple[Any, ...]] = []
    ri = 1

    for row in report.rows:
        rows.append(
            [
                row.entry_date,
                row.entry_number,
                row.account_name,
                row.fund_code,
                row.memo,
                _money(row.amount),
            ]
        )
        ri += 1

    # Grand total
    rows.append(["", "", "", "", "TOTAL", _money(report.grand_total)])
    extras += [
        ("BACKGROUND", (0, ri), (-1, ri), _NAVY),
        ("TEXTCOLOR", (0, ri), (-1, ri), colors.white),
        ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
    ]

    flowables.append(_build_table(rows, cw, extras, right_align_cols=[5]))

    doc = _doc(buf)
    doc.build(flowables)
    return buf.getvalue()


# ── 3. Expense Summary (YTD) ──────────────────────────────────────────────────


def render_expense_summary_pdf(report: YtdExpenseSummaryReport) -> bytes:
    """Expense Summary — YTD totals grouped by expense category group."""
    buf = io.BytesIO()
    styles = _styles()

    subtitle = f"{report.from_date} to {report.to_date}"
    flowables: list[Any] = _header_flowables("Expense Summary", subtitle, styles)

    # Column widths: Acct# | Account Name | YTD Amount | Trans  = 7.2"
    cw = [
        0.80 * inch,
        3.80 * inch,
        1.40 * inch,
        1.20 * inch,
    ]

    header = ["Acct #", "Account Name", "YTD Amount", "Trans"]
    rows: list[list[str]] = [header]
    extras: list[tuple[Any, ...]] = []
    ri = 1

    for group in report.groups:
        label = group.group_code or "General"

        # Group header
        rows.append([label, "", "", ""])
        extras += [
            ("BACKGROUND", (0, ri), (-1, ri), _GROUP_BG),
            ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
            ("SPAN", (0, ri), (-1, ri)),
        ]
        ri += 1

        for row in group.rows:
            rows.append(
                [
                    row.account_number,
                    f"  {row.account_name}",
                    _money(row.ytd_amount),
                    str(row.record_count),
                ]
            )
            ri += 1

        # Group subtotal
        rows.append(
            [
                "",
                f"{label} Total",
                _money(group.group_total),
                str(group.group_record_count),
            ]
        )
        extras += [
            ("BACKGROUND", (0, ri), (-1, ri), _GROUP_BG),
            ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
        ]
        ri += 1

    # Grand total
    rows.append(
        ["", "GRAND TOTAL", _money(report.grand_total), str(report.total_record_count)]
    )
    extras += [
        ("BACKGROUND", (0, ri), (-1, ri), _NAVY),
        ("TEXTCOLOR", (0, ri), (-1, ri), colors.white),
        ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
    ]

    flowables.append(_build_table(rows, cw, extras, right_align_cols=[2, 3]))

    doc = _doc(buf)
    doc.build(flowables)
    return buf.getvalue()


# ── 4. Budget Summary ─────────────────────────────────────────────────────────


def render_budget_summary_pdf(report: BudgetSummaryReport) -> bytes:
    """Budget Summary — annual budget amounts, optionally multi-year."""
    buf = io.BytesIO()
    styles = _styles()

    years_label = " · ".join(str(y) for y in report.years)
    subtitle = f"Fiscal Year(s): {years_label}"
    flowables: list[Any] = _header_flowables("Budget Summary", subtitle, styles)

    n = len(report.years)

    # Build column widths dynamically.
    # Category always gets the bulk of the space; each year gets 1.0",
    # each % change gets 0.6".  Total must equal _CW ≈ 7.2".
    year_col_w = 1.0 * inch
    pct_col_w = 0.60 * inch
    extra_cols = n * year_col_w + max(n - 1, 0) * pct_col_w
    cat_w = _CW - extra_cols
    cw = [cat_w]
    for i in range(n):
        cw.append(year_col_w)
        if i < n - 1:
            cw.append(pct_col_w)

    # Header row
    header: list[str] = ["Category"]
    for i, yr in enumerate(report.years):
        header.append(str(yr))
        if i < n - 1:
            header.append("Chg%")
    rows: list[list[str]] = [header]
    extras: list[tuple[Any, ...]] = []
    ri = 1

    right_cols = list(range(1, len(cw)))  # all numeric cols right-aligned

    for group in report.groups:
        label = group.group_code or "General"

        # Group header
        rows.append([label] + [""] * (len(cw) - 1))
        extras += [
            ("BACKGROUND", (0, ri), (-1, ri), _GROUP_BG),
            ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
            ("SPAN", (0, ri), (-1, ri)),
        ]
        ri += 1

        for row in group.rows:
            detail: list[str] = [f"  {row.category_name}"]
            for i, amt in enumerate(row.year_amounts):
                detail.append(_money(amt))
                if i < n - 1:
                    detail.append(row.pct_changes[i] if row.pct_changes else "")
            rows.append(detail)
            ri += 1

        # Group subtotal
        sub: list[str] = [f"{label} Total"]
        for i, amt in enumerate(group.subtotal_amounts):
            sub.append(_money(amt))
            if i < n - 1:
                pct = (
                    group.subtotal_pct_changes[i] if group.subtotal_pct_changes else ""
                )
                sub.append(pct)
        rows.append(sub)
        extras += [
            ("BACKGROUND", (0, ri), (-1, ri), _GROUP_BG),
            ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
        ]
        ri += 1

    # Grand total
    total_row: list[str] = ["GRAND TOTAL"]
    for i, amt in enumerate(report.total_amounts):
        total_row.append(_money(amt))
        if i < n - 1:
            pct = report.total_pct_changes[i] if report.total_pct_changes else ""
            total_row.append(pct)
    rows.append(total_row)
    extras += [
        ("BACKGROUND", (0, ri), (-1, ri), _NAVY),
        ("TEXTCOLOR", (0, ri), (-1, ri), colors.white),
        ("FONTNAME", (0, ri), (-1, ri), "Helvetica-Bold"),
    ]

    flowables.append(_build_table(rows, cw, extras, right_align_cols=right_cols))

    doc = _doc(buf)
    doc.build(flowables)
    return buf.getvalue()


# ── 5. Homeowner Contact List ─────────────────────────────────────────────────


def render_homeowner_contact_list_pdf(report: HomeownerContactListReport) -> bytes:
    """Homeowner Contact List — name, address, phones, email."""
    buf = io.BytesIO()
    styles = _styles()

    subtitle = f"Active homeowners as of {date.today().strftime('%B %d, %Y')}"
    flowables: list[Any] = _header_flowables("Homeowner Contact List", subtitle, styles)

    # Column widths: Name | Address | Cell | Email  = 7.2"
    cw = [
        1.60 * inch,
        2.00 * inch,
        1.20 * inch,
        2.40 * inch,
    ]

    header = ["Name", "Address", "Cell", "Email"]
    rows: list[list[str]] = [header]

    has_renter = False
    for row in report.rows:
        full_name = f"{row.first_name} {row.last_name}".strip()
        if row.role == "RENTER":
            full_name += " (R)"
            has_renter = True
        rows.append(
            [
                full_name,
                row.address,
                row.cell_phone,
                row.email,
            ]
        )

    flowables.append(_build_table(rows, cw, extra_styles=[], right_align_cols=None))

    if has_renter:
        footnote_style = ParagraphStyle(
            "Footnote",
            parent=getSampleStyleSheet()["Normal"],
            fontSize=7,
            leading=9,
            textColor=_MUTED,
            spaceBefore=6,
        )
        flowables.append(
            Paragraph("(R) Renter — property is occupied by a tenant, not the owner of record.", footnote_style)
        )

    doc = _doc(buf)
    doc.build(flowables)
    return buf.getvalue()

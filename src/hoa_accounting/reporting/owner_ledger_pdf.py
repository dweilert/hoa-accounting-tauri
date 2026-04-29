"""Owner-ledger PDF generator using ``reportlab``.

Renders the same data shape ``LotStatementReport`` as the previous
weasyprint+Jinja path produced, but in pure Python so the app can
ship without a Cairo / Pango / GDK-PixBuf native-library dependency.
This dramatically simplifies cross-platform packaging — see commit
message for the full migration story.

Layout intent matches the retired ``pdf_owner_ledger.html`` template:
title bar, four-up totals strip, owner-contact block, optional
beginning-balance breakdown, then the per-row transactions table.
The visual styling is intentionally close to the HTML version but not
pixel-identical — reportlab's flowable model and CSS box model are
different beasts.
"""

from __future__ import annotations

import io
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

# ── Colour palette (matches the HTML template) ────────────────────────
_NAVY = colors.HexColor("#1e3a5f")
_BORDER = colors.HexColor("#d1d9e0")
_PANEL_BG = colors.HexColor("#f5f7fa")
_MUTED = colors.HexColor("#6b7280")
_PAYMENT_BG = colors.HexColor("#dcfce7")
_PAYMENT_FG = colors.HexColor("#166534")
_LATE_BG = colors.HexColor("#fef3c7")
_LATE_FG = colors.HexColor("#92400e")
_LEGAL_BG = colors.HexColor("#fee2e2")
_LEGAL_FG = colors.HexColor("#991b1b")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "Title",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=18,
            textColor=_NAVY,
            spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "Meta",
            parent=base["Normal"],
            fontSize=9,
            leading=11,
            textColor=colors.HexColor("#555555"),
        ),
        "generated": ParagraphStyle(
            "Generated",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#999999"),
        ),
        "label": ParagraphStyle(
            "Label",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=_MUTED,
        ),
        "value": ParagraphStyle(
            "Value",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=14,
            textColor=_NAVY,
        ),
        "owner_name": ParagraphStyle(
            "OwnerName",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=14,
            textColor=colors.black,
        ),
        "owner_detail": ParagraphStyle(
            "OwnerDetail",
            parent=base["Normal"],
            fontSize=9,
            leading=12,
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            parent=base["Normal"],
            fontSize=8.5,
            leading=10,
        ),
        "table_cell_mono": ParagraphStyle(
            "TableCellMono",
            parent=base["Normal"],
            fontName="Courier",
            fontSize=8,
            leading=10,
        ),
        "empty": ParagraphStyle(
            "Empty",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            textColor=_MUTED,
            alignment=1,  # center
        ),
    }


def _pill(
    label: str, bg: colors.Color, fg: colors.Color, styles: dict[str, ParagraphStyle]
) -> Table:
    """Render a small coloured pill — Platypus has no native pill, so we
    fake one with a single-cell table that has rounded-feeling padding
    and a coloured background."""
    cell_style = ParagraphStyle(
        "Pill",
        parent=styles["table_cell"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=fg,
        alignment=1,
    )
    t = Table([[Paragraph(label, cell_style)]], colWidths=[None])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), bg),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return t


def _type_pill(row: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Any:
    """Pick the type-pill colour for a transaction row, mirroring the
    branching the HTML template did."""
    entry_type = row.get("entry_type", "")
    charge_type = row.get("charge_type", "")
    if entry_type == "PAYMENT":
        return _pill("Payment", _PAYMENT_BG, _PAYMENT_FG, styles)
    if entry_type == "ADJUSTMENT":
        return _pill("Adjustment", _PANEL_BG, _NAVY, styles)
    if charge_type == "LATE_FEE":
        return _pill("Late Fee", _LATE_BG, _LATE_FG, styles)
    if charge_type == "LEGAL_FEE":
        return _pill("Legal Fee", _LEGAL_BG, _LEGAL_FG, styles)
    return Paragraph(charge_type or "—", styles["table_cell"])


def _build_header(
    summary: dict[str, Any], styles: dict[str, ParagraphStyle]
) -> list[Any]:
    address = summary.get("lot_address") or ""
    hoa_name = summary.get("hoa_name") or ""
    meta_parts: list[str] = []
    if hoa_name:
        meta_parts.append(str(hoa_name))
    meta_parts.append(f"Lot {summary['lot_number']}")
    if address:
        meta_parts.append(address)
    meta_parts.append(f"Year {summary['year']}")
    flowables: list[Any] = [
        Paragraph("Owner Ledger", styles["title"]),
        Paragraph(" &nbsp;·&nbsp; ".join(meta_parts), styles["meta"]),
    ]
    if summary.get("generated_at"):
        flowables.append(
            Paragraph(
                f"Generated {summary['generated_at']}",
                styles["generated"],
            )
        )
    flowables.append(Spacer(1, 8))
    return flowables


def _build_totals_bar(
    summary: dict[str, Any], styles: dict[str, ParagraphStyle]
) -> Table:
    """Four-column 'Lot / Year / Opening / Closing' strip."""
    cols = [
        ("Lot", summary["lot_number"]),
        ("Year", summary["year"]),
        ("Opening Balance", summary["opening_balance"]),
        ("Closing Balance", summary["closing_balance"]),
    ]
    cells = [
        [Paragraph(label, styles["label"]), Paragraph(str(value), styles["value"])]
        for label, value in cols
    ]
    # Lay out as a 4-column row of mini-tables so each label/value pair
    # stacks vertically.
    inner_tables = [
        Table(
            [[c[0]], [c[1]]],
            colWidths=[1.6 * inch],
            style=TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            ),
        )
        for c in cells
    ]
    bar = Table([inner_tables], colWidths=[1.7 * inch] * 4)
    bar.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), _PANEL_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return bar


def _build_owner_block(
    summary: dict[str, Any], styles: dict[str, ParagraphStyle]
) -> list[Any]:
    owners = summary.get("owners") or []
    if not owners:
        return []

    label = "Owner" if len(owners) == 1 else "Owners"
    cards = []
    for o in owners:
        name = (
            f"{o.get('first_name', '')} {o.get('last_name', '')}".strip()
            or o.get("display_name", "")
            or "Unknown"
        )
        lines = [Paragraph(f"<b>{name}</b>", styles["owner_name"])]
        if o.get("email"):
            lines.append(
                Paragraph(
                    f'<font color="#6b7280">Email:</font> {o["email"]}',
                    styles["owner_detail"],
                )
            )
        if o.get("phone"):
            lines.append(
                Paragraph(
                    f'<font color="#6b7280">Phone:</font> {o["phone"]}',
                    styles["owner_detail"],
                )
            )
        cards.append(lines)

    # Lay out cards in a row (multi-owner grid).
    card_tables = [
        Table(
            [[ln] for ln in card],
            colWidths=[2.0 * inch],
            style=TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ]
            ),
        )
        for card in cards
    ]
    grid = Table([card_tables], colWidths=[2.1 * inch] * len(cards))
    grid.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    block = Table(
        [[Paragraph(label.upper(), styles["label"])], [grid]],
        colWidths=[6.8 * inch],
    )
    block.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return [block, Spacer(1, 8)]


def _build_opening_balance_block(
    summary: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    lines = summary.get("opening_balance_lines") or []
    if not lines:
        return []

    rows = [["Charge Type", "Balance"]]
    for line in lines:
        rows.append([line["label"], line["amount"]])
    rows.append(["Total Opening Balance", summary["opening_balance"]])

    table = Table(rows, colWidths=[5.0 * inch, 1.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (-1, 0), _MUTED),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, _BORDER),
                ("LINEABOVE", (0, -1), (-1, -1), 0.5, _BORDER),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (0, -1), (0, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    block = Table(
        [[Paragraph("BEGINNING BALANCE DETAIL", styles["label"])], [table]],
        colWidths=[6.8 * inch],
    )
    block.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, _BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return [block, Spacer(1, 8)]


def _build_transactions_table(
    summary: dict[str, Any],
    styles: dict[str, ParagraphStyle],
) -> list[Any]:
    rows = summary.get("rows") or []
    if not rows:
        return [
            Paragraph(
                f"No activity for this lot in {summary['year']}.",
                styles["empty"],
            )
        ]

    header = [
        "Date",
        "Type",
        "Description",
        "Receipt",
        "Charge",
        "Payment",
        "Balance",
    ]
    data: list[list[Any]] = [header]
    for row in rows:
        type_cell = _type_pill(row, styles)
        debit = row.get("debit_amount", "")
        credit = row.get("credit_amount", "")
        data.append(
            [
                Paragraph(row.get("entry_date", ""), styles["table_cell"]),
                type_cell,
                Paragraph(row.get("description", ""), styles["table_cell"]),
                Paragraph(
                    row.get("receipt_number", "") or "",
                    styles["table_cell_mono"],
                ),
                "" if debit == "0.00" else debit,
                "" if credit == "0.00" else credit,
                row.get("running_balance", ""),
            ]
        )
    data.append(
        [
            "Closing Balance",
            "",
            "",
            "",
            "",
            "",
            summary["closing_balance"],
        ]
    )

    col_widths = [
        0.65 * inch,  # Date
        0.85 * inch,  # Type  (wider so "Payment" pill doesn't wrap)
        3.20 * inch,  # Description
        0.70 * inch,  # Receipt
        0.55 * inch,  # Charge
        0.60 * inch,  # Payment
        0.65 * inch,  # Balance
    ]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    n = len(data)
    table.setStyle(
        TableStyle(
            [
                # Header row
                ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (-1, 0), "LEFT"),
                # Body styling
                ("FONTSIZE", (0, 1), (-1, -2), 8),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -2),
                    [colors.white, colors.HexColor("#fafbfc")],
                ),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, _BORDER),
                # Closing-balance row
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), _PANEL_BG),
                ("LINEABOVE", (0, -1), (-1, -1), 1, _NAVY),
                ("SPAN", (0, n - 1), (-2, n - 1)),
                ("ALIGN", (0, -1), (-2, -1), "RIGHT"),
                ("ALIGN", (-1, -1), (-1, -1), "RIGHT"),
                # Padding
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return [table]


def render_owner_ledger_pdf(summary: dict[str, Any]) -> bytes:
    """Build a one-PDF-per-lot owner-ledger document.

    ``summary`` matches the dict shape that
    :py:func:`hoa_accounting.reporting.batch_pdf._report_to_template_context`
    produces — keep this signature in sync with that helper.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
        title=f"Owner Ledger — Lot {summary['lot_number']} — {summary['year']}",
    )
    styles = _styles()
    story: list[Any] = []
    story.extend(_build_header(summary, styles))
    story.append(_build_totals_bar(summary, styles))
    story.append(Spacer(1, 8))
    story.extend(_build_owner_block(summary, styles))
    story.extend(_build_opening_balance_block(summary, styles))
    story.extend(_build_transactions_table(summary, styles))
    doc.build(story)
    return buf.getvalue()

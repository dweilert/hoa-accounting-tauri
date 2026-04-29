"""Generate a Reserve Fund Study Word document (.docx)."""

from __future__ import annotations

import io
from datetime import date
from decimal import Decimal, InvalidOperation

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor, Twips

from hoa_accounting.repositories.reserve_study_repo import ReserveStudyRepository
from hoa_accounting.web.reserve_study_pages import _compute_funding_plan, _q2


# ── Colour palette ────────────────────────────────────────────────────────────
_RED   = RGBColor(0xC0, 0x39, 0x2B)
_BLACK = RGBColor(0x00, 0x00, 0x00)
_GREY  = RGBColor(0x60, 0x60, 0x60)
_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
_DARK  = RGBColor(0x22, 0x22, 0x22)
_HEAD_BG = "2C3E50"   # dark slate — table header fill
_ALT_BG  = "F2F4F5"   # very light grey — alternating row


def _shade_cell(cell, hex_color: str) -> None:
    """Fill a table cell background with a hex colour (no #)."""
    from docx.oxml import OxmlElement
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _set_col_widths(table, widths_inches: list[float]) -> None:
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            if i < len(widths_inches):
                cell.width = Inches(widths_inches[i])


def _header_row(table, labels: list[str]) -> None:
    row = table.rows[0]
    for i, label in enumerate(labels):
        cell = row.cells[i]
        _shade_cell(cell, _HEAD_BG)
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(label)
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = _WHITE


def _money(v: Decimal) -> str:
    if v < 0:
        return f"(${abs(v):,.0f})"
    return f"${v:,.0f}"


def _pct(v: object) -> str:
    try:
        return f"{float(v) * 100:.1f}%"  # type: ignore[arg-type]
    except Exception:
        return "—"


def _chart_funding_gauge(pct_funded: float) -> io.BytesIO:
    """Half-donut gauge matching the UI style."""
    import numpy as np

    color = "#C0392B" if pct_funded < 30 else ("#D97706" if pct_funded < 70 else "#1E8449")
    capped = min(max(pct_funded, 0), 100)

    fig, ax = plt.subplots(figsize=(4.2, 2.8))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Pie trick: [funded%, unfunded%, 100] — last slice is the hidden bottom half
    # startangle=180 + counterclock=False → sweeps left→top→right (0%→50%→100%)
    sizes = [capped, 100 - capped, 100]
    pie_colors = [color, "#E5E7EB", "white"]
    wedges, _ = ax.pie(
        sizes,
        colors=pie_colors,
        startangle=180,
        counterclock=False,
        wedgeprops={"width": 0.38, "edgecolor": "white", "linewidth": 2},
    )
    wedges[2].set_alpha(0)  # hide bottom half

    # 70% benchmark tick mark
    # At 70%: 180° - (70/100 * 180°) = 54° in standard (CCW from east)
    bench_rad = np.radians(180 - 70 * 1.8)
    r_in, r_out = 0.63, 1.08
    ax.plot(
        [r_in * np.cos(bench_rad), r_out * np.cos(bench_rad)],
        [r_in * np.sin(bench_rad), r_out * np.sin(bench_rad)],
        color="#2C3E50", linewidth=2.5, zorder=5,
    )
    ax.text(
        1.22 * np.cos(bench_rad), 1.22 * np.sin(bench_rad) + 0.04,
        "70%\nbenchmark",
        fontsize=7.5, color="#2C3E50", ha="center", va="bottom", linespacing=1.3,
    )

    # Centre labels
    ax.text(0, -0.08, f"{pct_funded:.1f}%", ha="center", va="center",
            fontsize=22, fontweight="bold", color=color)
    ax.text(0, -0.30, "funded", ha="center", va="center",
            fontsize=10, color="#666666")

    ax.set_title("Percent Funded", fontsize=12, fontweight="bold",
                 color="#222222", pad=4)
    ax.set_ylim(-0.52, 1.28)
    ax.axis("off")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _chart_balance_projection(plan_rows: list[dict]) -> io.BytesIO:
    """Bar chart of ending reserve balance by year — green positive, red deficit."""
    years    = [r["year"] for r in plan_rows]
    balances = [float(r["ending_balance"]) for r in plan_rows]
    colors   = ["#1E8449" if b >= 0 else "#C0392B" for b in balances]

    fig, ax = plt.subplots(figsize=(6.5, 2.8))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    ax.bar(years, balances, color=colors, width=0.75, zorder=2)
    ax.axhline(y=0, color="#222222", linewidth=0.6, zorder=3)
    ax.set_title(f"{len(years)}-Year Reserve Balance Projection", fontsize=11,
                 fontweight="bold", color="#222222", pad=10)
    ax.set_xlabel("Year", fontsize=9, color="#444444")
    ax.set_ylabel("Balance", fontsize=9, color="#444444")
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"${v/1000:,.0f}k")
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", labelsize=8, colors="#555555")
    ax.tick_params(axis="y", labelsize=8, colors="#555555")
    ax.grid(axis="y", linestyle="--", linewidth=0.4, color="#DDDDDD", zorder=1)
    ax.legend(
        handles=[
            mpatches.Patch(color="#1E8449", label="Positive balance"),
            mpatches.Patch(color="#C0392B", label="Deficit year"),
        ],
        fontsize=8, loc="upper right", framealpha=0.8,
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _chart_expenditures(plan_rows: list[dict]) -> io.BytesIO:
    """Bar chart of planned capital expenditures by year."""
    years   = [r["year"] for r in plan_rows]
    amounts = [float(r["total_spent"]) for r in plan_rows]

    fig, ax = plt.subplots(figsize=(6.5, 2.5))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    ax.bar(years, amounts, color="#E67E22", width=0.75, zorder=2)
    ax.set_title("Planned Capital Expenditures by Year", fontsize=11,
                 fontweight="bold", color="#222222", pad=10)
    ax.set_xlabel("Year", fontsize=9, color="#444444")
    ax.set_ylabel("Amount", fontsize=9, color="#444444")
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"${v/1000:,.0f}k")
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", labelsize=8, colors="#555555")
    ax.tick_params(axis="y", labelsize=8, colors="#555555")
    ax.grid(axis="y", linestyle="--", linewidth=0.4, color="#DDDDDD", zorder=1)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_reserve_study_docx(
    repo: ReserveStudyRepository,
    org_name: str,
) -> bytes:
    """Build a full Reserve Fund Study Word document and return raw bytes."""
    doc = Document()

    # ── Page setup: 1-inch margins ────────────────────────────────────────
    section = doc.sections[0]
    section.top_margin    = Inches(1.0)
    section.bottom_margin = Inches(1.0)
    section.left_margin   = Inches(1.15)
    section.right_margin  = Inches(1.15)

    # Default body font
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)

    assumptions = repo.get_active_assumptions()
    assets = repo.list_assets()
    scenarios = repo.list_scenarios()

    if assumptions is None:
        doc.add_paragraph("Error: No active reserve study assumptions found.")
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    override = assumptions["reserve_balance_override"]
    opening_balance = _q2(override) if override is not None else repo.get_reserve_fund_balance()

    study_year     = int(assumptions["study_year"])
    num_lots       = int(assumptions["num_lots"])
    annual_contrib = _q2(assumptions["annual_contribution"])
    growth_rate    = _q2(assumptions["contribution_growth_rate"])
    invest_rate    = _q2(assumptions["investment_return_rate"])
    proj_years     = int(assumptions["projection_years"])

    total_cost = _q2(sum(_q2(a["replacement_cost"]) for a in assets))
    pct_funded = _q2(
        (opening_balance / total_cost * 100) if total_cost > 0 else Decimal("0")
    )
    per_lot_balance   = _q2(opening_balance / num_lots) if num_lots > 0 else Decimal("0")
    per_lot_liability = _q2(total_cost / num_lots) if num_lots > 0 else Decimal("0")
    per_lot_contrib   = _q2(annual_contrib / num_lots) if num_lots > 0 else Decimal("0")

    today_str = date.today().strftime("%B %Y")

    # Pre-compute funding plan (used for charts + funding plan section)
    plan_rows = _compute_funding_plan(
        assumptions=assumptions, assets=assets, opening_balance=opening_balance
    )

    # ════════════════════════════════════════════════════════════════════════
    # COVER PAGE
    # ════════════════════════════════════════════════════════════════════════
    doc.add_paragraph()  # top spacing
    doc.add_paragraph()

    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title_p.add_run("RESERVE FUND STUDY")
    run.bold = True
    run.font.size = Pt(22)
    run.font.color.rgb = _DARK

    sub_p = doc.add_paragraph()
    sub_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sub_r = sub_p.add_run(org_name)
    sub_r.font.size = Pt(14)
    sub_r.font.color.rgb = _GREY

    doc.add_paragraph()
    date_p = doc.add_paragraph()
    date_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    date_r = date_p.add_run(f"{today_str}  ·  Study Year {study_year}  ·  CONFIDENTIAL")
    date_r.font.size = Pt(10)
    date_r.font.color.rgb = _GREY
    date_r.italic = True

    doc.add_paragraph()

    # Status box (manual table, 1 row, 1 col)
    status_label = (
        "⚠  CRITICALLY UNDERFUNDED" if pct_funded < 30 else
        "BELOW INDUSTRY BENCHMARK"  if pct_funded < 70 else
        "ADEQUATELY FUNDED"
    )
    status_color = "C0392B" if pct_funded < 30 else ("D97706" if pct_funded < 70 else "1E8449")

    tbl = doc.add_table(rows=1, cols=1)
    cell = tbl.cell(0, 0)
    _shade_cell(cell, status_color)
    sp = cell.paragraphs[0]
    sp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sp.add_run(f"{status_label} — Reserves {_pct(pct_funded)} Funded")
    sr.bold = True
    sr.font.size = Pt(11)
    sr.font.color.rgb = _WHITE

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════════════════
    # 1. EXECUTIVE SUMMARY
    # ════════════════════════════════════════════════════════════════════════
    _h1(doc, "1. Executive Summary")

    doc.add_paragraph(
        f"This Reserve Fund Study was prepared for {org_name} for the study year "
        f"{study_year}. The purpose of this study is to evaluate the current financial "
        f"position of the association's reserve fund, assess the condition and remaining "
        f"life of common-area assets, and project a multi-year funding plan to ensure "
        f"adequate reserves are maintained for future capital expenditures."
    )

    doc.add_paragraph(
        f"The association consists of {num_lots} lots. As of the study date, the reserve "
        f"fund balance is {_money(opening_balance)}, representing {_money(per_lot_balance)} "
        f"per lot. The total current-dollar replacement liability for all inventoried "
        f"components is {_money(total_cost)}, resulting in a percent-funded ratio of "
        f"{_pct(pct_funded)}. Industry benchmarks consider reserves adequate at 70% or higher."
    )

    if pct_funded < 30:
        p = doc.add_paragraph()
        r = p.add_run(
            "The association is critically underfunded. Immediate action is recommended, "
            "including a significant increase in annual reserve contributions and/or a "
            "special assessment to address imminent capital replacement needs."
        )
        r.bold = True

    # Key metrics table
    doc.add_paragraph()
    metrics = [
        ("Reserve Balance", _money(opening_balance)),
        ("Total Replacement Liability (Current $)", _money(total_cost)),
        ("Percent Funded", _pct(pct_funded)),
        ("Annual Contribution to Reserves", _money(annual_contrib)),
        ("Annual Contribution per Lot", _money(per_lot_contrib)),
        ("Per-Lot Reserve Balance", _money(per_lot_balance)),
        ("Per-Lot Replacement Liability", _money(per_lot_liability)),
        ("Number of Lots", str(num_lots)),
    ]
    tbl = doc.add_table(rows=len(metrics) + 1, cols=2)
    tbl.style = "Table Grid"
    _header_row_2col(tbl, "Metric", "Amount")
    for i, (label, value) in enumerate(metrics):
        row = tbl.rows[i + 1]
        _cell_text(row.cells[0], label, bold=False, shade=_ALT_BG if i % 2 == 0 else None)
        _cell_text(row.cells[1], value, bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT,
                   shade=_ALT_BG if i % 2 == 0 else None)
    _set_col_widths(tbl, [3.8, 1.8])

    # ── Charts ──────────────────────────────────────────────────────────────
    doc.add_paragraph()
    _h2(doc, "Reserve Fund Visualizations")

    gauge_buf = _chart_funding_gauge(float(pct_funded))
    doc.add_picture(gauge_buf, width=Inches(5.0))

    doc.add_paragraph()
    balance_buf = _chart_balance_projection(plan_rows)
    doc.add_picture(balance_buf, width=Inches(6.3))

    doc.add_paragraph()
    expend_buf = _chart_expenditures(plan_rows)
    doc.add_picture(expend_buf, width=Inches(6.3))

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════════════════
    # 2. ASSET INVENTORY & CONDITION ASSESSMENT
    # ════════════════════════════════════════════════════════════════════════
    _h1(doc, "2. Asset Inventory & Condition Assessment")

    doc.add_paragraph(
        "The following table lists all inventoried capital components, their estimated "
        "remaining useful life, current replacement cost in today's dollars, and condition "
        "rating. Future replacement costs are inflated at the rate shown per component."
    )
    doc.add_paragraph()

    # Group assets
    groups: dict[str, list] = {}
    for a in assets:
        groups.setdefault(a["asset_group"], []).append(a)

    condition_pill = {"Excellent": "0c6b55", "Good": "1E8449", "Moderate": "D97706", "Poor": "C0392B", "Critical": "922B21"}

    cols = ["Component", "Install\nYear", "Useful\nLife", "Replace\nYear", "Condition",
            "2026 Cost", "Inflation", "Future Cost"]
    widths = [2.2, 0.65, 0.6, 0.65, 0.75, 0.85, 0.65, 0.85]

    for group_name, group_assets in groups.items():
        _h2(doc, group_name)
        tbl = doc.add_table(rows=1 + len(group_assets), cols=len(cols))
        tbl.style = "Table Grid"
        _header_row(tbl, cols)
        for i, a in enumerate(group_assets):
            row = tbl.rows[i + 1]
            replace_yr = int(a["install_year"]) + int(a["useful_life_years"])
            years_out  = max(0, replace_yr - study_year)
            inflation  = _q2(a["annual_inflation"])
            cost       = _q2(a["replacement_cost"])
            future     = _q2(cost * (1 + inflation) ** years_out) if cost > 0 else Decimal("0")

            shade = _ALT_BG if i % 2 == 0 else None
            _cell_text(row.cells[0], a["component"],                    shade=shade)
            _cell_text(row.cells[1], str(a["install_year"]),            shade=shade, align=WD_ALIGN_PARAGRAPH.CENTER)
            _cell_text(row.cells[2], f"{a['useful_life_years']} yr",    shade=shade, align=WD_ALIGN_PARAGRAPH.CENTER)
            _cell_text(row.cells[3], str(replace_yr),                   shade=shade, align=WD_ALIGN_PARAGRAPH.CENTER, bold=True)
            _cell_text(row.cells[4], a["condition"],                    shade=shade, align=WD_ALIGN_PARAGRAPH.CENTER,
                       color=condition_pill.get(a["condition"], "000000"))
            _cell_text(row.cells[5], _money(cost) if cost else "$0",   shade=shade, align=WD_ALIGN_PARAGRAPH.RIGHT)
            _cell_text(row.cells[6], f"{float(a['annual_inflation'])*100:.0f}%",
                       shade=shade, align=WD_ALIGN_PARAGRAPH.CENTER)
            _cell_text(row.cells[7], _money(future) if future else "$0",shade=shade, align=WD_ALIGN_PARAGRAPH.RIGHT)
        _set_col_widths(tbl, widths)
        doc.add_paragraph()

    # Totals
    p = doc.add_paragraph()
    run = p.add_run(f"Total Current Replacement Cost: {_money(total_cost)}")
    run.bold = True
    run.font.size = Pt(10)

    # Condition key
    doc.add_paragraph()
    _h2(doc, "Condition Rating Key")
    key_tbl = doc.add_table(rows=6, cols=2)
    key_tbl.style = "Table Grid"
    _header_row_2col(key_tbl, "Rating", "Description")
    for i, (rating, desc) in enumerate([
        ("Excellent", "New or recently replaced; no concerns for many years"),
        ("Good",      "Functioning well; no immediate concerns"),
        ("Moderate",  "Showing wear; plan for replacement within useful life"),
        ("Poor",      "Needs replacement soon; risk of failure"),
        ("Critical",  "Past useful life or at high risk of failure — immediate action needed"),
    ]):
        _cell_text(key_tbl.rows[i+1].cells[0], rating,
                   shade=_ALT_BG if i % 2 == 0 else None,
                   color=condition_pill.get(rating, "000000"), bold=True)
        _cell_text(key_tbl.rows[i+1].cells[1], desc,
                   shade=_ALT_BG if i % 2 == 0 else None)
    _set_col_widths(key_tbl, [1.0, 5.6])

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════════════════
    # 3. FUNDING PLAN
    # ════════════════════════════════════════════════════════════════════════
    _h1(doc, f"3. {proj_years}-Year Reserve Funding Plan")

    doc.add_paragraph(
        f"The table below projects the reserve fund balance over {proj_years} years, "
        f"beginning with the {study_year} opening balance of {_money(opening_balance)}. "
        f"Annual contributions start at {_money(annual_contrib)} and grow at "
        f"{_pct(growth_rate)} per year. Reserve fund balances earn "
        f"{_pct(invest_rate)} annually. Asset replacement costs are inflated from "
        f"current-dollar estimates at each component's individual inflation rate."
    )
    doc.add_paragraph()

    fp_cols = ["Year", "Beg. Balance", "Contribution", "Investment\nIncome",
               "Expenditures", "End Balance"]
    fp_widths = [0.5, 1.1, 1.05, 0.9, 2.55, 1.0]
    tbl = doc.add_table(rows=1 + len(plan_rows), cols=len(fp_cols))
    tbl.style = "Table Grid"
    _header_row(tbl, fp_cols)

    for i, pr in enumerate(plan_rows):
        row  = tbl.rows[i + 1]
        shade = _ALT_BG if i % 2 == 0 else None
        deficit = pr["deficit"]

        _cell_text(row.cells[0], str(pr["year"]),                align=WD_ALIGN_PARAGRAPH.CENTER,
                   shade=shade, bold=True)
        _cell_text(row.cells[1], _money(pr["beginning_balance"]),align=WD_ALIGN_PARAGRAPH.RIGHT,
                   shade=shade, color="C0392B" if pr["beginning_balance"] < 0 else None)
        _cell_text(row.cells[2], _money(pr["contribution"]),     align=WD_ALIGN_PARAGRAPH.RIGHT, shade=shade)
        inv = pr["investment_income"]
        _cell_text(row.cells[3], _money(inv) if inv else "—",    align=WD_ALIGN_PARAGRAPH.RIGHT, shade=shade)

        # Expenditures column — list each item
        exp_cell = row.cells[4]
        if shade:
            _shade_cell(exp_cell, shade)
        if pr["total_spent"] > 0:
            exp_p = exp_cell.paragraphs[0]
            exp_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            exp_r = exp_p.add_run(_money(pr["total_spent"]))
            exp_r.bold = True
            exp_r.font.size = Pt(8)
            for label, cost in pr["expenditures"]:
                detail_p = exp_cell.add_paragraph(f"  {label}: {_money(cost)}")
                detail_p.runs[0].font.size = Pt(7)
                detail_p.runs[0].font.color.rgb = _GREY
        else:
            _cell_text(exp_cell, "—", align=WD_ALIGN_PARAGRAPH.CENTER, shade=shade)

        _cell_text(row.cells[5], _money(pr["ending_balance"]),  align=WD_ALIGN_PARAGRAPH.RIGHT,
                   shade=shade, bold=True,
                   color="C0392B" if deficit else None)

    _set_col_widths(tbl, fp_widths)

    doc.add_paragraph()
    note_p = doc.add_paragraph()
    note_r = note_p.add_run(
        "Note: Negative balances (shown in parentheses) indicate a projected reserve deficit "
        "in that year. These years would require a special assessment or emergency borrowing "
        "if not addressed by increasing contributions in advance."
    )
    note_r.italic = True
    note_r.font.size = Pt(9)
    note_r.font.color.rgb = _GREY

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════════════════
    # 4. SCENARIO ANALYSIS
    # ════════════════════════════════════════════════════════════════════════
    _h1(doc, "4. Emergency Scenario Analysis")

    doc.add_paragraph(
        "The following scenarios model the financial impact if a major capital asset fails "
        f"before sufficient reserves are accumulated. Each scenario shows the emergency "
        f"replacement cost and the resulting special assessment that would be required, "
        f"divided equally across all {num_lots} lots."
    )
    doc.add_paragraph()

    sc_cols = ["Scenario", "Expected\nYear", "Emergency\nCost", "Special Assessment\nper Lot"]
    sc_widths = [3.0, 0.85, 1.0, 1.35]
    tbl = doc.add_table(rows=1 + len(scenarios), cols=len(sc_cols))
    tbl.style = "Table Grid"
    _header_row(tbl, sc_cols)

    for i, s in enumerate(scenarios):
        row  = tbl.rows[i + 1]
        shade = _ALT_BG if i % 2 == 0 else None
        cost    = _q2(s["emergency_cost"])
        per_lot = _q2(cost / num_lots) if num_lots > 0 else Decimal("0")

        sc_cell = row.cells[0]
        if shade:
            _shade_cell(sc_cell, shade)
        sc_p = sc_cell.paragraphs[0]
        sc_r = sc_p.add_run(s["scenario_name"])
        sc_r.bold = True
        sc_r.font.size = Pt(9)
        if s["description"]:
            desc_p = sc_cell.add_paragraph(s["description"])
            desc_p.runs[0].font.size = Pt(8)
            desc_p.runs[0].font.color.rgb = _GREY
        if s["notes"]:
            note_p2 = sc_cell.add_paragraph(s["notes"])
            note_p2.runs[0].font.size = Pt(7.5)
            note_p2.runs[0].italic = True
            note_p2.runs[0].font.color.rgb = _GREY

        yr = str(s["expected_year"]) if s["expected_year"] else "Unknown"
        _cell_text(row.cells[1], yr,            align=WD_ALIGN_PARAGRAPH.CENTER, shade=shade)
        _cell_text(row.cells[2], _money(cost),  align=WD_ALIGN_PARAGRAPH.RIGHT,  shade=shade)
        _cell_text(row.cells[3], _money(per_lot), align=WD_ALIGN_PARAGRAPH.RIGHT, shade=shade,
                   bold=True, color="C0392B")

    _set_col_widths(tbl, sc_widths)

    doc.add_paragraph()
    sc_note = doc.add_paragraph()
    sc_note_r = sc_note.add_run(
        f"Special assessment per lot = Emergency Cost ÷ {num_lots} lots. "
        "Assumes the full cost falls on current lot owners with no reserve offset."
    )
    sc_note_r.italic = True
    sc_note_r.font.size = Pt(9)
    sc_note_r.font.color.rgb = _GREY

    doc.add_page_break()

    # ════════════════════════════════════════════════════════════════════════
    # 5. STUDY ASSUMPTIONS & METHODOLOGY
    # ════════════════════════════════════════════════════════════════════════
    _h1(doc, "5. Study Assumptions & Methodology")

    _h2(doc, "Key Assumptions")
    assump_data = [
        ("Study Year",                str(study_year)),
        ("Number of Lots",            str(num_lots)),
        ("Opening Reserve Balance",   _money(opening_balance)),
        ("Annual Contribution",       _money(annual_contrib)),
        ("Contribution Growth Rate",  _pct(growth_rate)),
        ("Investment Return Rate",    _pct(invest_rate)),
        ("Projection Period",         f"{proj_years} years ({study_year}–{study_year + proj_years - 1})"),
        ("Default Asset Inflation",   "4.0% per year (per asset)"),
    ]
    tbl = doc.add_table(rows=len(assump_data) + 1, cols=2)
    tbl.style = "Table Grid"
    _header_row_2col(tbl, "Assumption", "Value")
    for i, (label, value) in enumerate(assump_data):
        shade = _ALT_BG if i % 2 == 0 else None
        _cell_text(tbl.rows[i+1].cells[0], label, shade=shade)
        _cell_text(tbl.rows[i+1].cells[1], value, shade=shade, align=WD_ALIGN_PARAGRAPH.RIGHT)
    _set_col_widths(tbl, [3.8, 1.8])

    _h2(doc, "Methodology")
    doc.add_paragraph(
        "Replacement costs are expressed in current (study-year) dollars. Future replacement "
        "costs are calculated by compounding current costs at each component's annual "
        "inflation rate for the number of years until the projected replacement date "
        "(install year + useful life)."
    )
    doc.add_paragraph(
        "The percent-funded ratio is calculated as the current reserve balance divided by "
        "the total current-dollar replacement liability. A ratio of 70% or higher is "
        "generally considered adequate by industry standards. A ratio below 30% is "
        "considered critically underfunded."
    )
    doc.add_paragraph(
        "The funding plan projects annual reserve balances by starting with the opening "
        "balance, adding the annual contribution (grown at the specified rate each year), "
        "adding investment income earned on the beginning-of-year balance, and subtracting "
        "scheduled asset expenditures in each replacement year."
    )

    if assumptions["notes"]:
        _h2(doc, "Study Notes")
        doc.add_paragraph(str(assumptions["notes"]))

    # ════════════════════════════════════════════════════════════════════════
    # FOOTER NOTE
    # ════════════════════════════════════════════════════════════════════════
    doc.add_paragraph()
    footer_p = doc.add_paragraph()
    footer_r = footer_p.add_run(
        f"This Reserve Fund Study was prepared for {org_name} for internal planning "
        "purposes. Replacement cost estimates are based on current market data and "
        "professional judgment. Actual future costs may differ. This document is "
        "CONFIDENTIAL and intended for distribution to lot owners and board members only."
    )
    footer_r.italic = True
    footer_r.font.size = Pt(8)
    footer_r.font.color.rgb = _GREY

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _h1(doc: Document, text: str) -> None:
    p = doc.add_heading(text, level=1)
    for run in p.runs:
        run.font.color.rgb = _DARK


def _h2(doc: Document, text: str) -> None:
    p = doc.add_heading(text, level=2)
    for run in p.runs:
        run.font.color.rgb = _DARK


def _header_row_2col(table, col1: str, col2: str) -> None:
    row = table.rows[0]
    for cell, label in zip(row.cells, [col1, col2]):
        _shade_cell(cell, _HEAD_BG)
        p = cell.paragraphs[0]
        run = p.add_run(label)
        run.bold = True
        run.font.size = Pt(9)
        run.font.color.rgb = _WHITE


def _cell_text(
    cell,
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    align: WD_ALIGN_PARAGRAPH = WD_ALIGN_PARAGRAPH.LEFT,
    shade: str | None = None,
    color: str | None = None,
    size: int = 9,
) -> None:
    if shade:
        _shade_cell(cell, shade)
    p = cell.paragraphs[0]
    p.alignment = align
    run = p.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    if color:
        r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
        run.font.color.rgb = RGBColor(r, g, b)

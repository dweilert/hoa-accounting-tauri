"""Reserve Study pages.

Routes:
  GET  /reserve-study                   — summary dashboard
  GET  /reserve-study/assumptions/edit  — edit assumptions
  POST /reserve-study/assumptions/edit  — save assumptions
  GET  /reserve-study/assets            — asset inventory
  GET  /reserve-study/assets/new        — new asset form
  POST /reserve-study/assets/new        — save new asset
  GET  /reserve-study/assets/<id>/edit  — edit asset form
  POST /reserve-study/assets/<id>/edit  — save edited asset
  POST /reserve-study/assets/<id>/delete
  GET  /reserve-study/funding-plan      — 30-year projection table
  GET  /reserve-study/scenarios         — scenario list
  GET  /reserve-study/scenarios/new     — new scenario form
  POST /reserve-study/scenarios/new     — save new scenario
  GET  /reserve-study/scenarios/<id>/edit
  POST /reserve-study/scenarios/<id>/edit
  POST /reserve-study/scenarios/<id>/delete
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from http import HTTPStatus

from hoa_accounting.repositories.reserve_study_repo import ReserveStudyRepository
from hoa_accounting.web.template_engine import render_template

_CONDITIONS = ["Excellent", "Good", "Moderate", "Poor", "Critical"]
_CONDITION_PILL = {
    "Excellent": "pill--excellent",
    "Good":     "pill--ok",
    "Moderate": "pill--warn",
    "Poor":     "pill--danger",
    "Critical": "pill--critical",
}


@dataclass(frozen=True)
class PageResponse:
    status_code: int
    body_html: str


def _q2(v: object) -> Decimal:
    try:
        return Decimal(str(v)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return Decimal("0.00")


def _fmt_currency(v: Decimal) -> str:
    if v < 0:
        return f"(${abs(v):,.0f})"
    return f"${v:,.0f}"


def _compute_funding_plan(
    *,
    assumptions: sqlite3.Row,
    assets: list[sqlite3.Row],
    opening_balance: Decimal,
) -> list[dict]:
    """Return a list of dicts, one per year, for the projection table."""
    study_year = int(assumptions["study_year"])
    projection_years = int(assumptions["projection_years"])
    annual_contribution = _q2(assumptions["annual_contribution"])
    growth_rate = _q2(assumptions["contribution_growth_rate"])
    investment_rate = _q2(assumptions["investment_return_rate"])

    # Build a lookup: replacement_year → list of (component_label, inflated_cost)
    expenditures: dict[int, list[tuple[str, Decimal]]] = {}
    for asset in assets:
        cost = _q2(asset["replacement_cost"])
        if cost == Decimal("0.00"):
            continue
        replace_year = int(asset["install_year"]) + int(asset["useful_life_years"])
        inflation = _q2(asset["annual_inflation"])
        years_out = replace_year - study_year
        if years_out < 0:
            years_out = 0
        inflated = cost * (1 + inflation) ** years_out
        inflated = _q2(inflated)
        label = f"{asset['asset_group']} — {asset['component']}"
        expenditures.setdefault(replace_year, []).append((label, inflated))

    rows = []
    balance = opening_balance
    contribution = annual_contribution

    for offset in range(projection_years):
        year = study_year + offset

        # Investment return on beginning balance (only if positive)
        investment_income = Decimal("0.00")
        if balance > 0 and investment_rate > 0:
            investment_income = _q2(balance * investment_rate)

        year_expenditures = expenditures.get(year, [])
        total_spent = sum(cost for _, cost in year_expenditures)
        total_spent = _q2(total_spent)

        ending_balance = _q2(balance + contribution + investment_income - total_spent)

        rows.append({
            "year":              year,
            "beginning_balance": balance,
            "contribution":      contribution,
            "investment_income": investment_income,
            "expenditures":      year_expenditures,
            "total_spent":       total_spent,
            "ending_balance":    ending_balance,
            "deficit":           ending_balance < 0,
        })

        balance = ending_balance
        # Grow contribution for next year
        contribution = _q2(contribution * (1 + growth_rate))

    return rows


def _compute_scenario_dues_impact(
    scenario: sqlite3.Row,
    plan_rows: list[dict],
    num_lots: int,
    study_year: int,
) -> dict:
    """Return dues-increase options for a scenario."""
    cost = _q2(scenario["emergency_cost"])
    expected_year = scenario["expected_year"]

    # Find projected reserve balance at expected year
    balance_at_year = Decimal("0.00")
    if expected_year:
        for row in plan_rows:
            if row["year"] == int(expected_year):
                balance_at_year = row["beginning_balance"]
                break

    shortfall = _q2(max(Decimal("0"), cost - balance_at_year))
    per_lot_lump = _q2(shortfall / num_lots) if num_lots > 0 else Decimal("0")

    years_to_save = int(expected_year) - study_year if expected_year else 0
    years_to_save = max(1, years_to_save)

    def annual_increase(spread_years: int) -> Decimal:
        if num_lots <= 0 or spread_years <= 0:
            return Decimal("0")
        return _q2(shortfall / num_lots / spread_years)

    options = []
    for yrs in [3, 5, 10]:
        ann = annual_increase(yrs)
        options.append({
            "years":   yrs,
            "annual":  ann,
            "monthly": _q2(ann / 12),
        })

    return {
        "scenario_name":    scenario["scenario_name"],
        "emergency_cost":   cost,
        "expected_year":    expected_year,
        "balance_at_year":  balance_at_year,
        "shortfall":        shortfall,
        "per_lot_lump":     per_lot_lump,
        "spread_options":   options,
        "has_year":         expected_year is not None,
    }


class ReserveStudyPages:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._repo = ReserveStudyRepository(conn)

    def _base_ctx(self, org: dict, theme: str, page_key: str = "reserve-study") -> dict:
        return {
            "active_nav": "reserve-study",
            "page_key":   page_key,
            "org":        org,
            "theme":      theme,
        }

    # ── Summary ───────────────────────────────────────────────────────

    def render_summary(self, *, org: dict, theme: str, flash_message: str = "") -> PageResponse:
        assumptions = self._repo.get_active_assumptions()
        assets = self._repo.list_assets()

        if assumptions is None:
            ctx = {**self._base_ctx(org, theme), "breadcrumb": "Reserve Study",
                   "error": "No active assumptions found.", "flash_message": flash_message}
            return PageResponse(HTTPStatus.OK, render_template("reserve_study_summary.html", ctx))

        # Determine opening balance
        override = assumptions["reserve_balance_override"]
        if override is not None:
            opening_balance = _q2(override)
            balance_source = "override"
        else:
            opening_balance = self._repo.get_reserve_fund_balance()
            balance_source = "gl"

        total_current_cost = _q2(sum(_q2(a["replacement_cost"]) for a in assets))
        num_lots = int(assumptions["num_lots"])
        percent_funded = (
            (opening_balance / total_current_cost * 100)
            if total_current_cost > 0 else Decimal("0")
        )
        per_lot = _q2(opening_balance / num_lots) if num_lots > 0 else Decimal("0")
        per_lot_liability = _q2(total_current_cost / num_lots) if num_lots > 0 else Decimal("0")

        # Count conditions
        condition_counts = {c: 0 for c in _CONDITIONS}
        for a in assets:
            c = a["condition"]
            if c in condition_counts:
                condition_counts[c] += 1

        funding_status = "CRITICAL" if percent_funded < 30 else (
            "LOW" if percent_funded < 70 else "ADEQUATE"
        )

        # Funding plan for charts
        plan_rows = _compute_funding_plan(
            assumptions=assumptions, assets=assets, opening_balance=opening_balance
        )
        chart_years       = [r["year"] for r in plan_rows]
        chart_balances    = [float(r["ending_balance"]) for r in plan_rows]
        chart_expenditures = [float(r["total_spent"]) for r in plan_rows]

        ctx = {
            **self._base_ctx(org, theme),
            "breadcrumb":         "Reserve Study",
            "flash_message":      flash_message,
            "assumptions":        dict(assumptions),
            "opening_balance":    opening_balance,
            "balance_source":     balance_source,
            "total_current_cost": total_current_cost,
            "percent_funded":     percent_funded,
            "per_lot":            per_lot,
            "per_lot_liability":  per_lot_liability,
            "num_lots":           num_lots,
            "condition_counts":   condition_counts,
            "funding_status":     funding_status,
            "asset_count":        len(assets),
            "chart_years":        chart_years,
            "chart_balances":     chart_balances,
            "chart_expenditures": chart_expenditures,
        }
        return PageResponse(HTTPStatus.OK, render_template("reserve_study_summary.html", ctx))

    # ── Assumptions edit ──────────────────────────────────────────────

    def render_assumptions_form(
        self, *, org: dict, theme: str, error: str = "", form_data: dict | None = None
    ) -> PageResponse:
        assumptions = self._repo.get_active_assumptions()
        fd = form_data or {}
        if assumptions and not form_data:
            fd = {
                "study_year":                 str(assumptions["study_year"]),
                "reserve_balance_override":   str(assumptions["reserve_balance_override"] or ""),
                "annual_contribution":        str(assumptions["annual_contribution"]),
                "contribution_growth_rate":   str(float(assumptions["contribution_growth_rate"]) * 100),
                "investment_return_rate":     str(float(assumptions["investment_return_rate"]) * 100),
                "num_lots":                   str(assumptions["num_lots"]),
                "projection_years":           str(assumptions["projection_years"]),
                "notes":                      str(assumptions["notes"] or ""),
            }
        ctx = {
            **self._base_ctx(org, theme, "reserve-assumptions"),
            "breadcrumb":   "Reserve Study / Assumptions",
            "assumptions":  dict(assumptions) if assumptions else {},
            "fd":           fd,
            "error":        error,
        }
        return PageResponse(HTTPStatus.OK, render_template("reserve_study_assumptions.html", ctx))

    def handle_save_assumptions(
        self, *, form_data: dict, org: dict, theme: str
    ) -> tuple[str | None, PageResponse | None]:
        assumptions = self._repo.get_active_assumptions()
        if assumptions is None:
            return None, self.render_assumptions_form(org=org, theme=theme,
                                                       error="No assumptions record found.",
                                                       form_data=form_data)
        try:
            study_year = int(form_data.get("study_year", "").strip())
        except ValueError:
            return None, self.render_assumptions_form(org=org, theme=theme,
                                                       error="Study year must be a number.",
                                                       form_data=form_data)
        try:
            annual_contribution = _q2(form_data.get("annual_contribution", "0").strip())
        except Exception:
            return None, self.render_assumptions_form(org=org, theme=theme,
                                                       error="Annual contribution must be a number.",
                                                       form_data=form_data)
        try:
            growth_pct = Decimal(form_data.get("contribution_growth_rate", "3").strip())
            growth_rate = (growth_pct / 100).quantize(Decimal("0.0001"))
        except Exception:
            growth_rate = Decimal("0.03")
        try:
            return_pct = Decimal(form_data.get("investment_return_rate", "1").strip())
            investment_rate = (return_pct / 100).quantize(Decimal("0.0001"))
        except Exception:
            investment_rate = Decimal("0.01")
        try:
            num_lots = int(form_data.get("num_lots", "1").strip())
        except ValueError:
            num_lots = 1
        try:
            projection_years = int(form_data.get("projection_years", "30").strip())
            projection_years = max(5, min(50, projection_years))
        except ValueError:
            projection_years = 30

        override_raw = form_data.get("reserve_balance_override", "").strip()
        if override_raw:
            try:
                reserve_balance_override: Decimal | None = _q2(override_raw)
            except Exception:
                reserve_balance_override = None
        else:
            reserve_balance_override = None

        notes = form_data.get("notes", "").strip()

        self._repo.update_assumptions(
            int(assumptions["id"]),
            study_year=study_year,
            reserve_balance_override=reserve_balance_override,
            annual_contribution=annual_contribution,
            contribution_growth_rate=growth_rate,
            investment_return_rate=investment_rate,
            num_lots=num_lots,
            projection_years=projection_years,
            notes=notes,
        )
        self.conn.commit()
        return "/reserve-study?msg=Assumptions+saved.", None

    # ── Asset inventory ───────────────────────────────────────────────

    def render_assets(self, *, org: dict, theme: str, flash_message: str = "") -> PageResponse:
        assets = self._repo.list_assets()
        # Group by asset_group for display
        groups: dict[str, list] = {}
        for a in assets:
            g = a["asset_group"]
            groups.setdefault(g, []).append(dict(a))

        total_current = _q2(sum(_q2(a["replacement_cost"]) for a in assets))

        ctx = {
            **self._base_ctx(org, theme, "reserve-assets"),
            "breadcrumb":      "Reserve Study / Asset Inventory",
            "groups":          groups,
            "total_current":   total_current,
            "flash_message":   flash_message,
            "condition_pill":  _CONDITION_PILL,
        }
        return PageResponse(HTTPStatus.OK, render_template("reserve_study_assets.html", ctx))

    def render_asset_form(
        self,
        asset_id: int | None = None,
        *,
        org: dict,
        theme: str,
        error: str = "",
        form_data: dict | None = None,
    ) -> PageResponse:
        asset = None
        if asset_id is not None:
            asset = self._repo.get_asset(asset_id)
            if asset is None:
                return PageResponse(HTTPStatus.NOT_FOUND, "<h1>Asset not found</h1>")

        fd = form_data or {}
        if asset and not form_data:
            fd = {
                "asset_group":       asset["asset_group"],
                "component":         asset["component"],
                "install_year":      str(asset["install_year"]),
                "useful_life_years": str(asset["useful_life_years"]),
                "condition":         asset["condition"],
                "replacement_cost":  str(asset["replacement_cost"]),
                "annual_inflation":  str(float(asset["annual_inflation"]) * 100),
                "notes":             asset["notes"] or "",
            }

        ctx = {
            **self._base_ctx(org, theme, "reserve-assets"),
            "breadcrumb":  "Reserve Study / Asset Inventory",
            "asset_id":    asset_id,
            "asset":       dict(asset) if asset else None,
            "fd":          fd,
            "error":       error,
            "conditions":  _CONDITIONS,
        }
        return PageResponse(HTTPStatus.OK, render_template("reserve_study_asset_form.html", ctx))

    def handle_save_asset(
        self,
        asset_id: int | None,
        *,
        form_data: dict,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        asset_group = form_data.get("asset_group", "").strip()
        component   = form_data.get("component", "").strip()
        condition   = form_data.get("condition", "Good").strip()

        if not asset_group or not component:
            return None, self.render_asset_form(asset_id, org=org, theme=theme,
                                                 error="Asset group and component are required.",
                                                 form_data=form_data)
        if condition not in _CONDITIONS:
            condition = "Good"

        try:
            install_year = int(form_data.get("install_year", "").strip())
        except ValueError:
            return None, self.render_asset_form(asset_id, org=org, theme=theme,
                                                 error="Install year must be a number.",
                                                 form_data=form_data)
        try:
            useful_life = int(form_data.get("useful_life_years", "").strip())
        except ValueError:
            return None, self.render_asset_form(asset_id, org=org, theme=theme,
                                                 error="Useful life must be a number.",
                                                 form_data=form_data)
        try:
            replacement_cost = _q2(form_data.get("replacement_cost", "0").strip())
        except Exception:
            replacement_cost = Decimal("0.00")
        try:
            inflation_pct = Decimal(form_data.get("annual_inflation", "4").strip())
            annual_inflation = (inflation_pct / 100).quantize(Decimal("0.0001"))
        except Exception:
            annual_inflation = Decimal("0.04")

        notes = form_data.get("notes", "").strip()

        if asset_id is None:
            self._repo.insert_asset(
                asset_group=asset_group, component=component,
                install_year=install_year, useful_life_years=useful_life,
                condition=condition, replacement_cost=replacement_cost,
                annual_inflation=annual_inflation, notes=notes,
            )
            self.conn.commit()
            return "/reserve-study/assets?msg=Asset+added.", None
        else:
            self._repo.update_asset(
                asset_id,
                asset_group=asset_group, component=component,
                install_year=install_year, useful_life_years=useful_life,
                condition=condition, replacement_cost=replacement_cost,
                annual_inflation=annual_inflation, notes=notes,
            )
            self.conn.commit()
            return "/reserve-study/assets?msg=Asset+saved.", None

    def handle_delete_asset(
        self, asset_id: int, *, org: dict, theme: str
    ) -> tuple[str | None, PageResponse | None]:
        self._repo.deactivate_asset(asset_id)
        self.conn.commit()
        return "/reserve-study/assets?msg=Asset+removed.", None

    # ── Funding plan ─────────────────────────────────────────────────

    def render_funding_plan(self, *, org: dict, theme: str) -> PageResponse:
        assumptions = self._repo.get_active_assumptions()
        assets = self._repo.list_assets()

        if assumptions is None:
            ctx = {**self._base_ctx(org, theme, "reserve-funding-plan"),
                   "breadcrumb": "Reserve Study / Funding Plan",
                   "error": "No active assumptions found.", "rows": []}
            return PageResponse(HTTPStatus.OK, render_template("reserve_study_funding_plan.html", ctx))

        override = assumptions["reserve_balance_override"]
        opening_balance = _q2(override) if override is not None else self._repo.get_reserve_fund_balance()

        rows = _compute_funding_plan(
            assumptions=assumptions, assets=assets, opening_balance=opening_balance
        )

        ctx = {
            **self._base_ctx(org, theme, "reserve-funding-plan"),
            "breadcrumb":       "Reserve Study / Funding Plan",
            "assumptions":      dict(assumptions),
            "opening_balance":  opening_balance,
            "rows":             rows,
            "fmt":              _fmt_currency,
        }
        return PageResponse(HTTPStatus.OK, render_template("reserve_study_funding_plan.html", ctx))

    # ── Scenarios ─────────────────────────────────────────────────────

    def render_scenarios(self, *, org: dict, theme: str, flash_message: str = "") -> PageResponse:
        scenarios = self._repo.list_scenarios()
        assumptions = self._repo.get_active_assumptions()
        num_lots = int(assumptions["num_lots"]) if assumptions else 16

        # Compute funding plan so we can look up projected balances per scenario
        assets = self._repo.list_assets()
        plan_rows: list[dict] = []
        study_year = 2026
        if assumptions is not None:
            study_year = int(assumptions["study_year"])
            override = assumptions["reserve_balance_override"]
            opening_balance = _q2(override) if override is not None else self._repo.get_reserve_fund_balance()
            plan_rows = _compute_funding_plan(
                assumptions=assumptions, assets=assets, opening_balance=opening_balance
            )

        rows = []
        dues_impacts = []
        for s in scenarios:
            cost = _q2(s["emergency_cost"])
            per_lot = _q2(cost / num_lots) if num_lots > 0 else Decimal("0")
            rows.append({**dict(s), "per_lot_assessment": per_lot})
            dues_impacts.append(
                _compute_scenario_dues_impact(s, plan_rows, num_lots, study_year)
            )

        ctx = {
            **self._base_ctx(org, theme, "reserve-scenarios"),
            "breadcrumb":    "Reserve Study / Scenario Analysis",
            "rows":          rows,
            "dues_impacts":  dues_impacts,
            "flash_message": flash_message,
            "num_lots":      num_lots,
        }
        return PageResponse(HTTPStatus.OK, render_template("reserve_study_scenarios.html", ctx))

    def render_scenario_form(
        self,
        scenario_id: int | None = None,
        *,
        org: dict,
        theme: str,
        error: str = "",
        form_data: dict | None = None,
    ) -> PageResponse:
        scenario = None
        if scenario_id is not None:
            scenario = self._repo.get_scenario(scenario_id)
            if scenario is None:
                return PageResponse(HTTPStatus.NOT_FOUND, "<h1>Scenario not found</h1>")

        fd = form_data or {}
        if scenario and not form_data:
            fd = {
                "scenario_name":  scenario["scenario_name"],
                "description":    scenario["description"] or "",
                "emergency_cost": str(scenario["emergency_cost"]),
                "expected_year":  str(scenario["expected_year"] or ""),
                "notes":          scenario["notes"] or "",
            }

        ctx = {
            **self._base_ctx(org, theme, "reserve-scenarios"),
            "breadcrumb":   "Reserve Study / Scenarios",
            "scenario_id":  scenario_id,
            "scenario":     dict(scenario) if scenario else None,
            "fd":           fd,
            "error":        error,
        }
        return PageResponse(HTTPStatus.OK, render_template("reserve_study_scenario_form.html", ctx))

    def handle_save_scenario(
        self,
        scenario_id: int | None,
        *,
        form_data: dict,
        org: dict,
        theme: str,
    ) -> tuple[str | None, PageResponse | None]:
        scenario_name = form_data.get("scenario_name", "").strip()
        if not scenario_name:
            return None, self.render_scenario_form(scenario_id, org=org, theme=theme,
                                                    error="Scenario name is required.",
                                                    form_data=form_data)
        description = form_data.get("description", "").strip()
        notes       = form_data.get("notes", "").strip()
        try:
            emergency_cost = _q2(form_data.get("emergency_cost", "0").strip())
        except Exception:
            emergency_cost = Decimal("0.00")
        expected_year_raw = form_data.get("expected_year", "").strip()
        expected_year: int | None = None
        if expected_year_raw:
            try:
                expected_year = int(expected_year_raw)
            except ValueError:
                pass

        if scenario_id is None:
            self._repo.insert_scenario(
                scenario_name=scenario_name, description=description,
                emergency_cost=emergency_cost, expected_year=expected_year, notes=notes,
            )
            self.conn.commit()
            return "/reserve-study/scenarios?msg=Scenario+added.", None
        else:
            self._repo.update_scenario(
                scenario_id,
                scenario_name=scenario_name, description=description,
                emergency_cost=emergency_cost, expected_year=expected_year, notes=notes,
            )
            self.conn.commit()
            return "/reserve-study/scenarios?msg=Scenario+saved.", None

    def handle_delete_scenario(
        self, scenario_id: int, *, org: dict, theme: str
    ) -> tuple[str | None, PageResponse | None]:
        self._repo.deactivate_scenario(scenario_id)
        self.conn.commit()
        return "/reserve-study/scenarios?msg=Scenario+removed.", None

    # ── HTML report preview ───────────────────────────────────────────

    def render_report_preview(self, *, org: dict, theme: str) -> PageResponse:
        from datetime import date

        assumptions = self._repo.get_active_assumptions()
        assets      = self._repo.list_assets()
        scenarios   = self._repo.list_scenarios()

        if assumptions is None:
            # The report template assumes the full data set; on the empty
            # path we render a small placeholder rather than feeding it
            # missing context vars.
            ctx = {**self._base_ctx(org, theme, "reserve-study"),
                   "breadcrumb": "Reserve Study / Report",
                   "heading": "Reserve Study Report",
                   "message": ("No active reserve study assumptions found. "
                               "Visit Reserve Fund Study → Assumptions to "
                               "enter study-year inputs first."),
                   "page_key": "reserve-study"}
            return PageResponse(HTTPStatus.OK, render_template("error.html", ctx))

        override = assumptions["reserve_balance_override"]
        opening_balance = _q2(override) if override is not None else self._repo.get_reserve_fund_balance()

        num_lots      = int(assumptions["num_lots"])
        total_cost    = _q2(sum(_q2(a["replacement_cost"]) for a in assets))
        percent_funded = _q2((opening_balance / total_cost * 100) if total_cost > 0 else Decimal("0"))
        per_lot_balance   = _q2(opening_balance / num_lots) if num_lots > 0 else Decimal("0")
        per_lot_liability = _q2(total_cost / num_lots)      if num_lots > 0 else Decimal("0")
        annual_contrib    = _q2(assumptions["annual_contribution"])
        per_lot_contrib   = _q2(annual_contrib / num_lots)  if num_lots > 0 else Decimal("0")

        funding_status = "CRITICAL" if percent_funded < 30 else (
            "LOW" if percent_funded < 70 else "ADEQUATE"
        )

        cover_metrics = [
            ("Reserve Balance",          f"${opening_balance:,.0f}"),
            ("Total Liability",           f"${total_cost:,.0f}"),
            ("Percent Funded",            f"{percent_funded:.1f}%"),
            ("Annual Contribution",       f"${annual_contrib:,.0f}"),
            ("Per-Lot Balance",           f"${per_lot_balance:,.0f}"),
            ("Per-Lot Liability",         f"${per_lot_liability:,.0f}"),
        ]

        summary_metrics = [
            ("Reserve Balance",                        f"${opening_balance:,.0f}"),
            ("Total Replacement Liability (Current $)", f"${total_cost:,.0f}"),
            ("Percent Funded",                          f"{percent_funded:.1f}%"),
            ("Annual Contribution to Reserves",         f"${annual_contrib:,.0f}"),
            ("Annual Contribution per Lot",             f"${per_lot_contrib:,.0f}"),
            ("Per-Lot Reserve Balance",                 f"${per_lot_balance:,.0f}"),
            ("Per-Lot Replacement Liability",           f"${per_lot_liability:,.0f}"),
            ("Number of Lots",                          str(num_lots)),
        ]

        assumption_rows = [
            ("Study Year",               str(assumptions["study_year"])),
            ("Number of Lots",           str(num_lots)),
            ("Opening Reserve Balance",  f"${opening_balance:,.0f}"),
            ("Annual Contribution",      f"${annual_contrib:,.0f}"),
            ("Contribution Growth Rate", f"{float(assumptions['contribution_growth_rate'])*100:.1f}%"),
            ("Investment Return Rate",   f"{float(assumptions['investment_return_rate'])*100:.1f}%"),
            ("Projection Period",        f"{assumptions['projection_years']} years"),
            ("Default Asset Inflation",  "4.0% per year (per asset)"),
        ]

        # Asset groups
        asset_groups: dict[str, list] = {}
        for a in assets:
            asset_groups.setdefault(a["asset_group"], []).append(a)

        condition_key = [
            ("Excellent", "pill--excellent", "New or recently replaced; no concerns for many years"),
            ("Good",      "pill--ok",        "Functioning well; no immediate concerns"),
            ("Moderate",  "pill--warn",      "Showing wear; plan for replacement within useful life"),
            ("Poor",      "pill--danger",    "Needs replacement soon; risk of failure"),
            ("Critical",  "pill--critical",  "Past useful life or at high risk of failure — immediate action needed"),
        ]

        plan_rows = _compute_funding_plan(
            assumptions=assumptions, assets=assets, opening_balance=opening_balance
        )

        study_year = int(assumptions["study_year"])
        sc_rows = []
        dues_impacts = []
        for s in scenarios:
            cost    = _q2(s["emergency_cost"])
            per_lot = _q2(cost / num_lots) if num_lots > 0 else Decimal("0")
            sc_rows.append({**dict(s), "per_lot_assessment": per_lot})
            dues_impacts.append(
                _compute_scenario_dues_impact(s, plan_rows, num_lots, study_year)
            )

        chart_years        = [r["year"] for r in plan_rows]
        chart_balances     = [float(r["ending_balance"]) for r in plan_rows]
        chart_expenditures = [float(r["total_spent"]) for r in plan_rows]

        ctx = {
            **self._base_ctx(org, theme, "reserve-study"),
            "breadcrumb":          "Reserve Study / Report",
            "assumptions":         dict(assumptions),
            "opening_balance":     opening_balance,
            "total_cost":          total_cost,
            "percent_funded":      percent_funded,
            "per_lot_balance":     per_lot_balance,
            "funding_status":      funding_status,
            "cover_metrics":       cover_metrics,
            "summary_metrics":     summary_metrics,
            "assumption_rows":     assumption_rows,
            "asset_groups":        asset_groups,
            "condition_pill":      _CONDITION_PILL,
            "condition_key":       condition_key,
            "plan_rows":           plan_rows,
            "scenario_rows":       sc_rows,
            "dues_impacts":        dues_impacts,
            "today":               date.today().strftime("%B %Y"),
            "chart_years":         chart_years,
            "chart_balances":      chart_balances,
            "chart_expenditures":  chart_expenditures,
        }
        return PageResponse(HTTPStatus.OK, render_template("reserve_study_report.html", ctx))

    # ── Word download ─────────────────────────────────────────────────

    def generate_word_report(self, *, org_name: str) -> bytes:
        from hoa_accounting.web.reserve_study_report import generate_reserve_study_docx
        return generate_reserve_study_docx(self._repo, org_name=org_name)

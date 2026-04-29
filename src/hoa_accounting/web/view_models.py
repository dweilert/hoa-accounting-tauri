"""UI-facing view-model builders for the web layer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date as _date
from typing import Any

from hoa_accounting.web.report_catalog import (
    REPORT_DEFINITIONS,
    ReportDefinition,
    get_report_definition,
)


@dataclass(frozen=True)
class ReportCardVM:
    """Home page quick-report card."""

    name: str
    title: str
    description: str
    example_query: str


@dataclass(frozen=True)
class ReportOptionVM:
    """Drop-down option for report selection."""

    name: str
    title: str
    selected: bool


@dataclass(frozen=True)
class ReportCatalogCardVM:
    """Catalog card shown on the report console."""

    title: str
    description: str
    field_list: str
    selected: bool


@dataclass(frozen=True)
class ParameterFieldVM:
    """One input row on the report console form."""

    name: str
    label: str
    value: str
    placeholder: str
    field_type: str = "text"  # "text" | "select"
    required: bool = False


@dataclass(frozen=True)
class HomePageContext:
    """Template context for the home page."""

    api_status: str
    report_cards: list[ReportCardVM]
    org: dict[str, object]
    active_nav: str
    breadcrumb: str
    selected_report: str
    theme: str


@dataclass(frozen=True)
class ReportConsoleContext:
    """Template context for the report console page."""

    report_options: list[ReportOptionVM]
    report_title: str
    report_description: str
    report_catalog_cards: list[ReportCatalogCardVM]
    parameter_fields: list[ParameterFieldVM]
    summary_template: str
    summary: dict[str, object]
    error_message: str
    raw_json: str
    org: dict[str, object]
    active_nav: str
    breadcrumb: str
    selected_report: str
    theme: str
    lookup_options: dict[str, Any] = dc_field(default_factory=dict[str, Any])


_DEFAULT_ORG: dict[str, object] = {
    "name": "HOA Accounting",
    "legal_name": "",
    "environment": "local",
    "fiscal_year_start_month": 1,
    "theme": "warm",
}


def _resolve_theme(org: dict[str, object] | None) -> str:
    if not org:
        return "warm"
    theme = org.get("theme")
    return str(theme) if theme else "warm"


def build_home_page_context(
    *,
    api_status: str,
    org: dict[str, object] | None = None,
) -> HomePageContext:
    """Build the context for the dashboard home page."""
    return HomePageContext(
        api_status=api_status,
        report_cards=[
            ReportCardVM(
                name=report_def.name,
                title=report_def.title,
                description=report_def.description,
                example_query=_example_query_for_report(report_def.name),
            )
            for report_def in REPORT_DEFINITIONS
        ],
        org=org or dict(_DEFAULT_ORG),
        active_nav="home",
        breadcrumb="Overview",
        selected_report="",
        theme=_resolve_theme(org),
    )


def build_report_console_context(
    *,
    selected_report: str,
    form_values: dict[str, str],
    summary_template: str,
    summary: dict[str, object],
    error_message: str,
    api_payload: dict[str, object] | None,
    org: dict[str, object] | None = None,
    lookup_options: dict[str, Any] | None = None,
) -> ReportConsoleContext:
    """Build the template context for the report console page."""
    report_def = get_report_definition(selected_report)

    return ReportConsoleContext(
        report_options=_build_report_options(selected_report),
        report_title=report_def.title,
        report_description=report_def.description,
        report_catalog_cards=_build_report_catalog_cards(selected_report),
        parameter_fields=_build_parameter_fields(
            report_def=report_def,
            form_values=form_values,
        ),
        summary_template=summary_template,
        summary=summary,
        error_message=error_message,
        raw_json=_build_raw_json(api_payload),
        org=org or dict(_DEFAULT_ORG),
        active_nav="reports",
        # Intentionally blank — the heading already says 'Reports' and
        # the sidebar shows we're on the Reports tab, so a breadcrumb
        # reading 'REPORTS' above a heading reading 'Reports' just
        # duplicates the word.
        breadcrumb="",
        selected_report=report_def.name,
        theme=_resolve_theme(org),
        lookup_options=lookup_options or {},
    )


def _build_report_options(selected_report: str) -> list[ReportOptionVM]:
    return [
        ReportOptionVM(
            name=report_def.name,
            title=report_def.title,
            selected=report_def.name == selected_report,
        )
        for report_def in REPORT_DEFINITIONS
    ]


def _build_report_catalog_cards(selected_report: str) -> list[ReportCatalogCardVM]:
    cards: list[ReportCatalogCardVM] = []
    for report_def in REPORT_DEFINITIONS:
        cards.append(
            ReportCatalogCardVM(
                title=report_def.title,
                description=report_def.description,
                field_list=", ".join(field.label for field in report_def.fields),
                selected=report_def.name == selected_report,
            )
        )
    return cards


def _date_field_default(field_name: str) -> str:
    year = _date.today().year
    defaults = {
        "from_date": f"{year}-01-01",
        "to_date": f"{year}-12-31",
        "year": str(year),
        "fiscal_year": str(year),
    }
    return defaults.get(field_name, "")


def _build_parameter_fields(
    *,
    report_def: ReportDefinition,
    form_values: dict[str, str],
) -> list[ParameterFieldVM]:
    fields: list[ParameterFieldVM] = []
    for field in report_def.fields:
        required_marker = " *" if field.required else ""
        raw_value = form_values.get(field.name, field.default_value)
        if not raw_value and field.field_type == "text":
            raw_value = _date_field_default(field.name)
        fields.append(
            ParameterFieldVM(
                name=field.name,
                label=field.label + required_marker,
                value=raw_value,
                placeholder=field.placeholder,
                field_type=field.field_type,
                required=field.required,
            )
        )
    return fields


def _build_raw_json(api_payload: dict[str, object] | None) -> str:
    if api_payload is None:
        return ""
    return json.dumps(api_payload, indent=2, sort_keys=True)


def _example_query_for_report(report_name: str) -> str:
    examples = {
        "ytd-expense-summary": "&from_date=2026-01-01&to_date=2026-12-31",
        "income-by-date": "&from_date=2026-01-01&to_date=2026-12-31",
        "expenses-by-date": "&from_date=2026-01-01&to_date=2026-12-31",
        "vendor-expenses": "&from_date=2026-01-01&to_date=2026-12-31",
        "expenses-vs-budget": "&fiscal_year=2026&fund_code=operating",
        "owner-ledger": "&lot_id=1&year=2026",
        "ar-aging": "&as_of_date=2026-03-31",
    }
    return examples.get(report_name, "")

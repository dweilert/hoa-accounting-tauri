from hoa_accounting.web.template_engine import render_template


def test_render_template_uses_jinja_templates() -> None:
    output = render_template(
        "home.html",
        {
            "api_status": "READY",
            "report_cards": [
                {
                    "name": "trial-balance",
                    "title": "Trial Balance",
                    "description": "Basic financial balance check.",
                    "example_query": "&as_of_date=2026-01-31",
                }
            ],
            "org": {
                "name": "Test HOA",
                "legal_name": "Test HOA Inc.",
                "environment": "local",
                "fiscal_year_start_month": 1,
            },
            "active_nav": "home",
            "breadcrumb": "Overview",
            "selected_report": "",
        },
    )

    assert "Test HOA" in output
    assert "Trial Balance" in output
    assert "READY" in output

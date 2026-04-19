from hoa_accounting.web.template_engine import render_template


def test_render_template_uses_jinja_templates() -> None:
    output = render_template(
        "home.html",
        {
            "org": {
                "name": "Test HOA",
                "legal_name": "Test HOA Inc.",
                "environment": "local",
                "fiscal_year_start_month": 1,
            },
            "theme": "warm",
            "active_nav": "home",
            "heading": "Dashboard",
            "breadcrumb": "Overview",
            "hoa_name": "Test HOA Inc.",
            "bank_tiles": [],
            "last_recon": None,
            "budget_tile": None,
            "last_auto_backup": None,
            "cards": [],
            "fiscal_year": 2026,
        },
    )

    assert "Test HOA" in output
    assert "Dashboard" in output

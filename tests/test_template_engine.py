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
        },
    )

    assert "HOA Accounting Dashboard" in output
    assert "Trial Balance" in output
    assert "READY" in output
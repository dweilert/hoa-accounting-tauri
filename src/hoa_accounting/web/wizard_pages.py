"""Stub: chart-of-accounts wizard retired. Categories drive classification."""

from __future__ import annotations


class WizardAdminPages:
    def __init__(self, conn=None) -> None:  # noqa: ARG002
        pass

    def render_list(self, **_):  # type: ignore[no-untyped-def]
        return type("R", (), {"status_code": 410, "body_html": "<h1>Wizard retired</h1>"})()

    def render_groups(self, **_):  # type: ignore[no-untyped-def]
        return self.render_list()

    def render_options(self, **_):  # type: ignore[no-untyped-def]
        return self.render_list()

    def handle_save_group(self, **_):  # type: ignore[no-untyped-def]
        return ("/", None)

    def handle_save_option(self, **_):  # type: ignore[no-untyped-def]
        return ("/", None)


class WizardPages(WizardAdminPages):
    pass

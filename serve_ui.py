"""Entry point for the minimal report UI server."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from hoa_accounting.api.report_api import ReportAPIService
from hoa_accounting.application.report_runner import ReportRunner
from hoa_accounting.web.ui_server import HomePageService, ReportConsolePageService


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser for UI server startup."""
    parser = argparse.ArgumentParser(description="Run HOA accounting report UI.")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8090,
        help="Bind port (default: 8090)",
    )
    return parser


class UIRequestHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for the report console UI."""

    home_service: HomePageService
    report_page_service: ReportConsolePageService

    def do_GET(self) -> None:
        parsed = urlparse(self.path)

        if parsed.path == "/":
            response = self.home_service.render_page()
            self._write_html(response.status_code, response.body_html)
            return

        if parsed.path == "/reports":
            raw_params = parse_qs(parsed.query)
            report_name = raw_params.get("report_name", ["trial-balance"])[-1]
            response = self.report_page_service.render_page(selected_report=report_name)
            self._write_html(response.status_code, response.body_html)
            return

        if parsed.path == "/run-report":
            raw_params = parse_qs(parsed.query)
            query_params = {
                key: values[-1]
                for key, values in raw_params.items()
                if values and values[-1].strip() != ""
            }
            report_name = query_params.pop("report_name", "").strip()

            response = self.report_page_service.render_report(
                report_name=report_name,
                query_params=query_params,
            )
            self._write_html(response.status_code, response.body_html)
            return

        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Not found")

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        """Keep default server logging simple."""
        super().log_message(format, *args)

    def _write_html(self, status_code: int, body_html: str) -> None:
        payload = body_html.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    """Run the UI server."""
    args = build_parser().parse_args()

    runner = ReportRunner(config_path=args.config)
    api_service = ReportAPIService(runner)

    base_dir = Path(__file__).resolve().parent / "src" / "hoa_accounting" / "web" / "templates"
    home_template_path = base_dir / "home.html"
    report_template_path = base_dir / "report_console.html"

    home_service = HomePageService(api_service, template_path=home_template_path)
    report_page_service = ReportConsolePageService(
        api_service,
        template_path=report_template_path,
    )

    class ConfiguredHandler(UIRequestHandler):
        pass

    ConfiguredHandler.home_service = home_service
    ConfiguredHandler.report_page_service = report_page_service

    server = ThreadingHTTPServer((args.host, args.port), ConfiguredHandler)
    print(f"Serving HOA accounting UI on http://{args.host}:{args.port}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down UI server...")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
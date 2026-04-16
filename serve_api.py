"""HTTP server entry point for the HOA accounting API."""

from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from hoa_accounting.api.report_api import ReportAPIService
from hoa_accounting.application.report_runner import ReportRunner


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser for API server startup."""
    parser = argparse.ArgumentParser(description="Run HOA accounting API server.")
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
        default=8080,
        help="Bind port (default: 8080)",
    )
    return parser


class ReportAPIRequestHandler(BaseHTTPRequestHandler):
    """HTTP adapter for report API requests."""

    api_service: ReportAPIService

    def do_GET(self) -> None:
        """Handle GET requests."""
        parsed = urlparse(self.path)

        if parsed.path == "/api/health":
            response = self.api_service.get_health()
            self._write_json(response.status_code, response.body)
            return

        if parsed.path.startswith("/api/reports/"):
            report_name = parsed.path.removeprefix("/api/reports/").strip("/")
            query_params = self._flatten_query_params(parse_qs(parsed.query))
            response = self.api_service.get_report(
                report_name=report_name,
                query_params=query_params,
            )
            self._write_json(response.status_code, response.body)
            return

        self._write_json(
            HTTPStatus.NOT_FOUND,
            {
                "ok": False,
                "error": {
                    "type": "not_found",
                    "message": f"Route not found: {parsed.path}",
                },
            },
        )

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        """Keep default server logging simple."""
        super().log_message(format, *args)

    def _flatten_query_params(self, raw_params: dict[str, list[str]]) -> dict[str, str]:
        return {
            key: values[-1]
            for key, values in raw_params.items()
            if values and values[-1].strip() != ""
        }

    def _write_json(self, status_code: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    """Run the API server."""
    args = build_parser().parse_args()

    runner = ReportRunner(config_path=args.config)
    api_service = ReportAPIService(runner)

    class ConfiguredHandler(ReportAPIRequestHandler):
        pass

    ConfiguredHandler.api_service = api_service

    server = ThreadingHTTPServer((args.host, args.port), ConfiguredHandler)
    print(f"Serving HOA accounting API on http://{args.host}:{args.port}")
    print("Available endpoints:")
    print("  GET /api/health")
    print("  GET /api/reports/<report-name>?<params>")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
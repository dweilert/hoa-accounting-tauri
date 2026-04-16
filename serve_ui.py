"""Entry point for the HOA accounting web UI (Flask)."""

from __future__ import annotations

import argparse

from hoa_accounting.web.app import create_app


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
        help="Bind host (default: 127.0.0.1 — local only)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8090,
        help="Bind port (default: 8090)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable Flask debug mode (auto-reload, tracebacks in browser).",
    )
    return parser


def main() -> int:
    """Run the UI server."""
    args = build_parser().parse_args()

    app = create_app(config_path=args.config)
    print(f"Serving HOA accounting UI on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

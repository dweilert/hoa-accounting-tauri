"""Command-line entry point for running accounting reports."""

from __future__ import annotations

import argparse
import json
import sys

from hoa_accounting.application.report_runner import ReportRunner
from hoa_accounting.exceptions import AccountingError


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Run HOA accounting reports.",
    )
    parser.add_argument(
        "report_name",
        help=(
            "Report name: trial-balance, general-ledger, owner-ledger, "
            "ar-aging, balance-sheet, income-statement"
        ),
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument("--as-of-date", dest="as_of_date")
    parser.add_argument("--from-date", dest="from_date")
    parser.add_argument("--to-date", dest="to_date")
    parser.add_argument("--account-id", dest="account_id")
    parser.add_argument("--owner-id", dest="owner_id")
    parser.add_argument(
        "--receivable-account-id",
        dest="receivable_account_id",
    )
    parser.add_argument(
        "--format",
        choices=["json"],
        default="json",
        help="Output format (currently json only).",
    )
    return parser


def main() -> int:
    """Run the CLI."""
    parser = build_parser()
    args = parser.parse_args()

    runner = ReportRunner(config_path=args.config)
    try:
        result = runner.run(
            args.report_name,
            as_of_date=args.as_of_date,
            from_date=args.from_date,
            to_date=args.to_date,
            account_id=args.account_id,
            owner_id=args.owner_id,
            receivable_account_id=args.receivable_account_id,
        )
    except AccountingError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.data, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
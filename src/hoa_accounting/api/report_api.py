"""Thin API layer for report execution."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from hoa_accounting.application.report_runner import ReportRunner
from hoa_accounting.exceptions import AccountingError, NotFoundError, ValidationError


@dataclass(frozen=True)
class APIResponse:
    """Structured API response."""

    status_code: int
    body: dict[str, Any]


class ReportAPIService:
    """Translate report-runner behavior into API-style responses."""

    def __init__(self, runner: ReportRunner) -> None:
        self.runner = runner

    def get_health(self) -> APIResponse:
        """Simple health response."""
        return APIResponse(
            status_code=HTTPStatus.OK,
            body={
                "ok": True,
                "service": "hoa-accounting-api",
                "status": "ready",
            },
        )

    def get_report(
        self,
        *,
        report_name: str,
        query_params: dict[str, str],
    ) -> APIResponse:
        """Execute a report and return an API-style JSON response."""
        try:
            result = self.runner.run(report_name, **query_params)
        except ValidationError as exc:
            return APIResponse(
                status_code=HTTPStatus.BAD_REQUEST,
                body={
                    "ok": False,
                    "error": {
                        "type": "validation_error",
                        "message": str(exc),
                    },
                },
            )
        except NotFoundError as exc:
            return APIResponse(
                status_code=HTTPStatus.NOT_FOUND,
                body={
                    "ok": False,
                    "error": {
                        "type": "not_found",
                        "message": str(exc),
                    },
                },
            )
        except AccountingError as exc:
            return APIResponse(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                body={
                    "ok": False,
                    "error": {
                        "type": "accounting_error",
                        "message": str(exc),
                    },
                },
            )
        except Exception as exc:  # pragma: no cover
            return APIResponse(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                body={
                    "ok": False,
                    "error": {
                        "type": "internal_error",
                        "message": str(exc),
                    },
                },
            )

        return APIResponse(
            status_code=HTTPStatus.OK,
            body={
                "ok": True,
                "report_name": result.report_name,
                "parameters": result.parameters,
                "data": result.data,
            },
        )

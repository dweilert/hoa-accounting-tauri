"""Helpers for serializing reporting DTOs."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from decimal import Decimal
from typing import Any


def to_plain_data(value: Any) -> Any:
    """Convert DTOs and Decimal values into JSON-safe plain data."""
    if is_dataclass(value) and not isinstance(value, type):
        return to_plain_data(asdict(value))

    if isinstance(value, dict):
        return {str(key): to_plain_data(item) for key, item in value.items()}

    if isinstance(value, list):
        return [to_plain_data(item) for item in value]

    if isinstance(value, tuple):
        return [to_plain_data(item) for item in value]

    if isinstance(value, Decimal):
        return str(value)

    return value

"""Repository for simple existence checks."""

from __future__ import annotations

from hoa_accounting.exceptions import ValidationError

from .base import BaseRepository

_ALLOWED_TABLES: frozenset[str] = frozenset({
    "lots",
    "owners",
    "vendors",
    "bank_accounts",
    "vendor_bills",
    "accounts",
})


class EntitiesRepository(BaseRepository):
    """Shared existence checks for common tables."""

    def exists(self, table_name: str, entity_id: int) -> bool:
        """Return True if the record exists."""
        if table_name not in _ALLOWED_TABLES:
            raise ValidationError(f"Unknown entity table: {table_name!r}")
        row = self.conn.execute(
            f"SELECT id FROM {table_name} WHERE id = ?",  # table validated above
            (entity_id,),
        ).fetchone()
        return row is not None

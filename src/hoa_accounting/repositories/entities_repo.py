"""Repository for simple existence checks."""

from __future__ import annotations

from .base import BaseRepository


class EntitiesRepository(BaseRepository):
    """Shared existence checks for common tables."""

    def exists(self, table_name: str, entity_id: int) -> bool:
        """Return True if the record exists."""
        row = self.conn.execute(
            f"SELECT id FROM {table_name} WHERE id = ?",
            (entity_id,),
        ).fetchone()
        return row is not None

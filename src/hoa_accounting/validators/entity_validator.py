"""Validation for required entities."""

from __future__ import annotations

from hoa_accounting.exceptions import NotFoundError
from hoa_accounting.repositories.entities_repo import EntitiesRepository


class EntityValidator:
    """Validation that required records exist."""

    def __init__(self, entities_repo: EntitiesRepository) -> None:
        self.entities_repo = entities_repo

    def require_exists(self, table_name: str, entity_id: int) -> None:
        """Raise if a required entity does not exist."""
        if not self.entities_repo.exists(table_name, entity_id):
            raise NotFoundError(f"{table_name} record {entity_id} was not found.")

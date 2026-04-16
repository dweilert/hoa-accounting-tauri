"""Core journal posting service."""

from __future__ import annotations

import sqlite3

from hoa_accounting.models.dto import JournalEntryResult, JournalLineInput
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.validators.common import q2
from hoa_accounting.validators.journal_validator import JournalValidator
from hoa_accounting.validators.period_validator import PeriodValidator


class JournalService:
    """Owns journal posting logic and audit writing."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        journal_repo: JournalRepository,
        audit_repo: AuditRepository,
        period_validator: PeriodValidator,
        journal_validator: JournalValidator,
    ) -> None:
        self.conn = conn
        self.journal_repo = journal_repo
        self.audit_repo = audit_repo
        self.period_validator = period_validator
        self.journal_validator = journal_validator

    def post_journal_entry(
        self,
        *,
        entry_date: str,
        source_type: str,
        memo: str,
        lines: list[JournalLineInput],
        created_by_user_id: int | None = None,
    ) -> JournalEntryResult:
        """Create and post a balanced journal entry."""
        accounting_period_id = self.period_validator.require_open_period(entry_date)
        self.journal_validator.validate_lines(lines)

        entry_number = self.journal_repo.next_entry_number(entry_date)
        journal_entry_id = self.journal_repo.insert_journal_entry(
            entry_number=entry_number,
            entry_date=entry_date,
            accounting_period_id=accounting_period_id,
            source_type=source_type,
            memo=memo,
            created_by_user_id=created_by_user_id,
        )
        self.journal_repo.insert_journal_lines(
            journal_entry_id=journal_entry_id,
            lines=lines,
            amount_formatter=q2,
        )

        self.audit_repo.write(
            entity_type="journal_entries",
            entity_id=journal_entry_id,
            action="POST",
            user_id=created_by_user_id,
            after_json={
                "entry_number": entry_number,
                "entry_date": entry_date,
                "source_type": source_type,
                "memo": memo,
                "line_count": len(lines),
            },
        )
        return JournalEntryResult(
            journal_entry_id=journal_entry_id,
            entry_number=entry_number,
            source_type=source_type,
        )

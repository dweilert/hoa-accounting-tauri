"""Journal-entry reversal workflow.

Scope is the accounting primitive: post a new journal entry whose lines
are the original's debits and credits swapped, and mark the original as
REVERSED with a pointer to the reversal. No business-record cascade — if
the reversed entry was tied to an assessment, vendor bill, or payment,
the corresponding business row is untouched here and should be adjusted
by its own service (follow-up work tracked per source type).

Why reverse instead of edit: editing a posted entry erases audit history.
A reversal leaves both entries on the books and balances them out.

Reversal date semantics: the reversal JE is posted with a caller-supplied
date. Standard practice is to post on the date the error is discovered,
not the original entry date — that avoids reopening closed periods and
keeps the audit trail honest. The caller is responsible for picking a
date in an open accounting period.
"""

from __future__ import annotations

import sqlite3

from hoa_accounting.db.transaction import transaction
from hoa_accounting.exceptions import NotFoundError, ValidationError
from hoa_accounting.models.dto import JournalLineInput, ReversalResult
from hoa_accounting.models.enums import SourceType
from hoa_accounting.repositories.audit_repo import AuditRepository
from hoa_accounting.repositories.journal_repo import JournalRepository
from hoa_accounting.services.journal_service import JournalService
from hoa_accounting.validators.common import q2


class ReversalService:
    """Reverse a previously posted journal entry."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        journal_repo: JournalRepository,
        audit_repo: AuditRepository,
        journal_service: JournalService,
    ) -> None:
        self.conn = conn
        self.journal_repo = journal_repo
        self.audit_repo = audit_repo
        self.journal_service = journal_service

    def reverse_journal_entry(
        self,
        *,
        journal_entry_id: int,
        reversal_date: str,
        memo: str | None = None,
        created_by_user_id: int | None = None,
    ) -> ReversalResult:
        """Post a reversing entry for an existing POSTED journal entry.

        Raises:
            NotFoundError: the original entry does not exist.
            ValidationError: the original is DRAFT or already REVERSED.
        """
        with transaction(self.conn):
            original = self.journal_repo.get_journal_entry(journal_entry_id)
            if original is None:
                raise NotFoundError(
                    f"Journal entry {journal_entry_id} was not found."
                )
            original_status = str(original["status"])
            if original_status != "POSTED":
                raise ValidationError(
                    f"Cannot reverse journal entry {journal_entry_id}: "
                    f"status is {original_status}, expected POSTED."
                )

            original_entry_number = str(original["entry_number"])
            original_lines = self.journal_repo.get_journal_lines(journal_entry_id)
            if not original_lines:
                # Should not happen for a POSTED entry given schema constraints,
                # but guard so a corrupt row can't create an empty reversal.
                raise ValidationError(
                    f"Journal entry {journal_entry_id} has no lines to reverse."
                )

            reversal_memo = memo or f"Reversal of {original_entry_number}"
            swapped_lines = [
                JournalLineInput(
                    account_id=int(line["account_id"]),
                    description=(
                        str(line["description"])
                        if line["description"] is not None
                        else reversal_memo
                    ),
                    debit_amount=q2(line["credit_amount"]),
                    credit_amount=q2(line["debit_amount"]),
                    lot_id=(
                        int(line["lot_id"]) if line["lot_id"] is not None else None
                    ),
                    owner_id=(
                        int(line["owner_id"])
                        if line["owner_id"] is not None
                        else None
                    ),
                    vendor_id=(
                        int(line["vendor_id"])
                        if line["vendor_id"] is not None
                        else None
                    ),
                    # Preserve the original tag so a reversed expense line
                    # reports under the same classification bucket.
                    expense_classification=(
                        str(line["expense_classification"])
                        if line["expense_classification"] is not None
                        else None
                    ),
                )
                for line in original_lines
            ]

            reversal_journal = self.journal_service.post_journal_entry(
                entry_date=reversal_date,
                source_type=SourceType.REVERSAL.value,
                memo=reversal_memo,
                created_by_user_id=created_by_user_id,
                lines=swapped_lines,
            )
            # Point the reversal entry at the original via source_id so the
            # audit trail is navigable in both directions.
            self.journal_repo.set_source_id(
                journal_entry_id=reversal_journal.journal_entry_id,
                source_id=journal_entry_id,
            )
            self.journal_repo.mark_reversed(
                journal_entry_id=journal_entry_id,
                reversal_entry_id=reversal_journal.journal_entry_id,
            )

            self.audit_repo.write(
                entity_type="journal_entries",
                entity_id=journal_entry_id,
                action="REVERSE",
                user_id=created_by_user_id,
                before_json={"status": "POSTED"},
                after_json={
                    "status": "REVERSED",
                    "reversal_entry_id": reversal_journal.journal_entry_id,
                    "reversal_entry_number": reversal_journal.entry_number,
                },
            )

            return ReversalResult(
                original_journal_entry_id=journal_entry_id,
                reversal_journal_entry_id=reversal_journal.journal_entry_id,
                reversal_entry_number=reversal_journal.entry_number,
            )

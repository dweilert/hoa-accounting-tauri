"""Repository for journal entries and journal lines."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, UTC

from hoa_accounting.exceptions import AccountingError
from hoa_accounting.models.dto import JournalLineInput

from .base import BaseRepository


_MAX_ENTRY_NUMBER_ATTEMPTS = 5


class JournalRepository(BaseRepository):
    """Database access for journal posting."""

    def next_entry_number(self, entry_date: str) -> str:
        """Generate the next journal entry number for a posting date.

        Derived from the currently-stored maximum for the same date. This is
        only a candidate — two concurrent posters can read the same max, so
        callers must handle a UNIQUE-constraint collision by retrying. Use
        ``insert_journal_entry_with_generated_number`` to do that safely.
        """
        date_part = entry_date.replace("-", "")
        prefix = f"JE-{date_part}-"
        row = self.conn.execute(
            """
            SELECT entry_number
            FROM journal_entries
            WHERE entry_number LIKE ?
            ORDER BY entry_number DESC
            LIMIT 1
            """,
            (f"{prefix}%",),
        ).fetchone()
        if row is None:
            next_num = 1
        else:
            last_entry = str(row["entry_number"])
            next_num = int(last_entry.split("-")[-1]) + 1
        return f"{prefix}{next_num:04d}"

    def insert_journal_entry(
        self,
        *,
        entry_number: str,
        entry_date: str,
        accounting_period_id: int,
        source_type: str,
        memo: str,
        created_by_user_id: int | None,
    ) -> int:
        """Insert a posted journal entry and return its id."""
        cur = self.conn.execute(
            """
            INSERT INTO journal_entries (
                entry_number,
                entry_date,
                accounting_period_id,
                source_type,
                source_id,
                memo,
                status,
                created_by_user_id,
                approved_by_user_id,
                posted_at
            ) VALUES (?, ?, ?, ?, NULL, ?, 'POSTED', ?, ?, ?)
            """,
            (
                entry_number,
                entry_date,
                accounting_period_id,
                source_type,
                memo,
                created_by_user_id,
                created_by_user_id,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
        return int(cur.lastrowid)

    def insert_journal_entry_with_generated_number(
        self,
        *,
        entry_date: str,
        accounting_period_id: int,
        source_type: str,
        memo: str,
        created_by_user_id: int | None,
    ) -> tuple[int, str]:
        """Insert a journal entry, retrying on entry_number collision.

        Handles the race where two concurrent posters compute the same
        ``next_entry_number`` by catching the UNIQUE constraint violation,
        rolling back the failed insert via a per-attempt SAVEPOINT, and
        computing a fresh candidate number. The outer transaction (whether
        real or savepoint-based) is not disturbed.

        Returns (journal_entry_id, entry_number).
        """
        last_exc: sqlite3.IntegrityError | None = None
        for _ in range(_MAX_ENTRY_NUMBER_ATTEMPTS):
            sp_name = f"je_{uuid.uuid4().hex}"
            self.conn.execute(f"SAVEPOINT {sp_name}")
            entry_number = self.next_entry_number(entry_date)
            try:
                journal_entry_id = self.insert_journal_entry(
                    entry_number=entry_number,
                    entry_date=entry_date,
                    accounting_period_id=accounting_period_id,
                    source_type=source_type,
                    memo=memo,
                    created_by_user_id=created_by_user_id,
                )
            except sqlite3.IntegrityError as exc:
                self.conn.execute(f"ROLLBACK TO SAVEPOINT {sp_name}")
                self.conn.execute(f"RELEASE SAVEPOINT {sp_name}")
                if "entry_number" not in str(exc):
                    # A different integrity problem — don't mask it.
                    raise
                last_exc = exc
                continue
            self.conn.execute(f"RELEASE SAVEPOINT {sp_name}")
            return journal_entry_id, entry_number

        raise AccountingError(
            "Could not allocate a unique journal entry number after "
            f"{_MAX_ENTRY_NUMBER_ATTEMPTS} attempts: {last_exc}"
        )

    def insert_journal_lines(
        self,
        *,
        journal_entry_id: int,
        lines: list[JournalLineInput],
        amount_formatter,
    ) -> None:
        """Insert journal lines for a posted journal entry."""
        for idx, line in enumerate(lines, start=1):
            self.conn.execute(
                """
                INSERT INTO journal_entry_lines (
                    journal_entry_id,
                    line_number,
                    account_id,
                    lot_id,
                    owner_id,
                    vendor_id,
                    description,
                    debit_amount,
                    credit_amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    journal_entry_id,
                    idx,
                    line.account_id,
                    line.lot_id,
                    line.owner_id,
                    line.vendor_id,
                    line.description,
                    str(amount_formatter(line.debit_amount)),
                    str(amount_formatter(line.credit_amount)),
                ),
            )

    def set_source_id(self, *, journal_entry_id: int, source_id: int) -> None:
        """Update a journal entry to reference its business source record."""
        self.conn.execute(
            "UPDATE journal_entries SET source_id = ? WHERE id = ?",
            (source_id, journal_entry_id),
        )

"""Repository for journal entries and journal lines."""

from __future__ import annotations

from datetime import datetime, UTC

from hoa_accounting.models.dto import JournalLineInput

from .base import BaseRepository


class JournalRepository(BaseRepository):
    """Database access for journal posting."""

    def next_entry_number(self, entry_date: str) -> str:
        """Generate the next journal entry number for a posting date."""
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

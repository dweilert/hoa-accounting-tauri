-- Migration 0011: Opening balances sub-ledger
--
-- Stores one opening-balance record per bank account and per lot.
-- A single OPENING_BALANCE journal entry ties all entries to the GL.
-- Also ensures an EQUITY account type exists for the offset account.

BEGIN TRANSACTION;

-- Equity account type (id=3 is the gap left by the existing 1,2,4,5 set)
INSERT OR IGNORE INTO account_types (id, code, name, normal_balance, financial_statement_group)
VALUES (3, 'EQUITY', 'Equity', 'CREDIT', 'BALANCE_SHEET');

CREATE TABLE IF NOT EXISTS opening_balances (
    id               INTEGER PRIMARY KEY,
    entity_type      TEXT    NOT NULL CHECK (entity_type IN ('BANK_ACCOUNT', 'LOT')),
    entity_id        INTEGER NOT NULL,
    as_of_date       TEXT    NOT NULL,
    amount           NUMERIC NOT NULL DEFAULT 0,
    journal_entry_id INTEGER REFERENCES journal_entries(id),
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (entity_type, entity_id)
);

COMMIT;

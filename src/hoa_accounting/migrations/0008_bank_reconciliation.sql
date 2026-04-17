-- Migration 0008: Bank reconciliation support
--
-- 1. Add opening-balance fields to bank_accounts so the first reconciliation
--    has a starting point that represents history before this system.
-- 2. Create reconciliation_clears which links a reconciliation to the specific
--    journal-entry lines the user checks off against the bank statement.
--    (bank_reconciliation_lines in 0001 was designed for a bank-feed/import
--    workflow; reconciliation_clears works directly against the GL.)

BEGIN TRANSACTION;

ALTER TABLE bank_accounts
    ADD COLUMN opening_balance      NUMERIC NOT NULL DEFAULT 0;

ALTER TABLE bank_accounts
    ADD COLUMN opening_balance_date TEXT;           -- ISO date, nullable

CREATE TABLE IF NOT EXISTS reconciliation_clears (
    reconciliation_id       INTEGER NOT NULL
        REFERENCES bank_reconciliations(id) ON DELETE CASCADE,
    journal_entry_line_id   INTEGER NOT NULL
        REFERENCES journal_entry_lines(id),
    PRIMARY KEY (reconciliation_id, journal_entry_line_id)
);

COMMIT;

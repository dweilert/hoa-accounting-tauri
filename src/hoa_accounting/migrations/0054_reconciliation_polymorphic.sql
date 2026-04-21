-- Migration 0054: Reconciliation redesign for single-entry sources.
--
-- Old reconciliation data is wiped (user directive — it was built on the
-- retired double-entry model and is no longer meaningful).
--
-- reconciliation_clears becomes polymorphic: each clear points at one of
-- {PAYMENT, INCOME_BATCH, BILL_PAYMENT, RESERVE_TRANSFER} by source_type
-- plus source_id.
--
-- bank_transactions gets matched_source_type / matched_source_id columns
-- so each imported bank line can link directly to the system record that
-- represents it. Legacy columns (matched_line_id, matched_journal_entry_id,
-- created_je_id) are kept nullable for compatibility but are no longer
-- written.
--
-- bank_transaction_rules gets vendor_id so expense-type rules can post
-- vendor bills + bill payments through the normal single-entry services.

BEGIN TRANSACTION;

-- 1. Wipe old reconciliation state — this system is being rebuilt from scratch.
DELETE FROM reconciliation_clears;
DELETE FROM bank_reconciliation_lines;
DELETE FROM bank_transactions;
DELETE FROM bank_import_batches;
DELETE FROM bank_reconciliations;

-- 2. Drop and recreate reconciliation_clears with polymorphic source columns.
DROP TABLE reconciliation_clears;
CREATE TABLE reconciliation_clears (
    id                INTEGER PRIMARY KEY,
    reconciliation_id INTEGER NOT NULL
        REFERENCES bank_reconciliations(id) ON DELETE CASCADE,
    source_type       TEXT    NOT NULL
        CHECK (source_type IN ('PAYMENT','INCOME_BATCH','BILL_PAYMENT','RESERVE_TRANSFER')),
    source_id         INTEGER NOT NULL,
    cleared_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (reconciliation_id, source_type, source_id)
);
CREATE INDEX idx_reconciliation_clears_recon
    ON reconciliation_clears(reconciliation_id);
CREATE INDEX idx_reconciliation_clears_source
    ON reconciliation_clears(source_type, source_id);

-- 3. Polymorphic match reference on bank_transactions.
ALTER TABLE bank_transactions
    ADD COLUMN matched_source_type TEXT;
ALTER TABLE bank_transactions
    ADD COLUMN matched_source_id INTEGER;

-- 4. vendor_id on bank_transaction_rules (required for expense action types).
ALTER TABLE bank_transaction_rules
    ADD COLUMN vendor_id INTEGER REFERENCES vendors(id);

COMMIT;

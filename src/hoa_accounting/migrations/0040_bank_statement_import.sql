-- Migration 0010: Extend bank import tables for reconciliation-linked statement import
--
-- bank_import_batches gets a reconciliation link, format flag, and counts.
-- bank_transactions gets memo, transaction_type, and a matched GL line reference.

BEGIN TRANSACTION;

ALTER TABLE bank_import_batches ADD COLUMN reconciliation_id INTEGER
    REFERENCES bank_reconciliations(id) ON DELETE CASCADE;
ALTER TABLE bank_import_batches ADD COLUMN file_format    TEXT    NOT NULL DEFAULT '';
ALTER TABLE bank_import_batches ADD COLUMN transaction_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bank_import_batches ADD COLUMN matched_count   INTEGER NOT NULL DEFAULT 0;

ALTER TABLE bank_transactions ADD COLUMN memo             TEXT    NOT NULL DEFAULT '';
ALTER TABLE bank_transactions ADD COLUMN transaction_type TEXT    NOT NULL DEFAULT '';
ALTER TABLE bank_transactions ADD COLUMN matched_line_id  INTEGER
    REFERENCES journal_entry_lines(id);

COMMIT;

-- Migration 0053: Add category_id to bank_transactions
-- Allows category-based transaction rules to tag bank transactions
-- for reporting without requiring a GL journal entry.

BEGIN TRANSACTION;

ALTER TABLE bank_transactions
    ADD COLUMN category_id INTEGER REFERENCES categories(id);

INSERT INTO schema_version (version, applied_at)
VALUES ('0053_bank_transactions_category.sql', datetime('now'));

COMMIT;

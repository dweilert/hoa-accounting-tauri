-- Migration 0041: Transaction rules + persistent bank import staging
--
-- 1. bank_import_batches: add status ('PENDING'|'APPLIED'), raw file bytes,
--    and CSV column map so the upload can be re-parsed without re-uploading.
-- 2. bank_transactions: add match_type, batch_match_ids (JSON), rule_id,
--    created_je_id to support rule-based JE creation and batch deposit matching.
-- 3. bank_transaction_rules: saved patterns → auto-create journal entries.

BEGIN TRANSACTION;

ALTER TABLE bank_import_batches ADD COLUMN status       TEXT NOT NULL DEFAULT 'PENDING';
ALTER TABLE bank_import_batches ADD COLUMN file_content BLOB;
ALTER TABLE bank_import_batches ADD COLUMN csv_col_map  TEXT NOT NULL DEFAULT '{}';

ALTER TABLE bank_transactions ADD COLUMN match_type      TEXT NOT NULL DEFAULT 'UNMATCHED';
ALTER TABLE bank_transactions ADD COLUMN batch_match_ids TEXT NOT NULL DEFAULT '[]';
ALTER TABLE bank_transactions ADD COLUMN rule_id         INTEGER REFERENCES bank_transaction_rules(id);
ALTER TABLE bank_transactions ADD COLUMN created_je_id   INTEGER REFERENCES journal_entries(id);

CREATE TABLE IF NOT EXISTS bank_transaction_rules (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name            TEXT    NOT NULL,
    description_contains TEXT    NOT NULL DEFAULT '',
    action_type          TEXT    NOT NULL DEFAULT 'direct_expense'
                             CHECK (action_type IN ('direct_expense', 'direct_income')),
    gl_account_id        INTEGER REFERENCES accounts(id),
    default_memo         TEXT    NOT NULL DEFAULT '',
    active_flag          INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    created_at           TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMIT;

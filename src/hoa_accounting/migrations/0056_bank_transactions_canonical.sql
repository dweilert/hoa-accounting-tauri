-- Migration 0056: Make bank_transactions the canonical per-bank-line record.
--
-- Shifts the system from "one bank_transactions row per batch line" to "one
-- row per unique bank transaction, identified by FITID (or a soft key when
-- FITID is absent)." A new bank_transaction_links table records the 0..N
-- ledger records associated with each bank line. Rules grow a confidence
-- model so new rules start in review-first mode and can be promoted.
--
-- Existing rows keep a 'legacy:<id>' dedup_key so the new unique constraint
-- doesn't fight historical data. Going forward the ingest code writes
-- 'fitid:<x>' or 'soft:<hash>' keys.

BEGIN TRANSACTION;

-- 1. Dedup key + validation status on bank_transactions.
ALTER TABLE bank_transactions
    ADD COLUMN dedup_key TEXT NOT NULL DEFAULT '';
ALTER TABLE bank_transactions
    ADD COLUMN validation_status TEXT NOT NULL DEFAULT 'UNVALIDATED';
    -- Allowed: 'UNVALIDATED', 'VALIDATED', 'IGNORED'. Enforced in app code
    -- (SQLite ALTER can't add CHECK constraints portably).

-- 2. Backfill dedup_key for any existing rows with a legacy-prefixed id so
--    they don't collide with each other or with future fitid/soft keys.
UPDATE bank_transactions
   SET dedup_key = 'legacy:' || id
 WHERE dedup_key = '';

-- 3. Unique index that guarantees one canonical row per (account, key).
CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_transactions_dedup
    ON bank_transactions(bank_account_id, dedup_key);

-- 4. Queue lookup index for the Pending Validation screen.
CREATE INDEX IF NOT EXISTS idx_bank_transactions_validation
    ON bank_transactions(validation_status, bank_account_id, transaction_date);

-- 5. bank_transaction_links: 0..N ledger records per bank line.
CREATE TABLE bank_transaction_links (
    id                    INTEGER PRIMARY KEY,
    bank_transaction_id   INTEGER NOT NULL
        REFERENCES bank_transactions(id) ON DELETE CASCADE,
    ledger_source_type    TEXT    NOT NULL,
        -- One of: 'PAYMENT', 'INCOME_BATCH', 'BILL_PAYMENT',
        -- 'RESERVE_TRANSFER', 'JOURNAL_ENTRY'. Matches the polymorphic
        -- source_type vocabulary used by reconciliation_clears so a single
        -- linker can render both.
    ledger_source_id      INTEGER NOT NULL,
    link_source           TEXT    NOT NULL DEFAULT 'MANUAL',
        -- 'RULE' | 'MANUAL' | 'AUTO_FIND' | 'RECONCILE'. Tells the UI who
        -- decided the link so the user can retract rule-based links without
        -- touching manual ones.
    rule_id               INTEGER REFERENCES bank_transaction_rules(id),
    created_at            TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (bank_transaction_id, ledger_source_type, ledger_source_id)
);

CREATE INDEX idx_bank_transaction_links_txn
    ON bank_transaction_links(bank_transaction_id);
CREATE INDEX idx_bank_transaction_links_source
    ON bank_transaction_links(ledger_source_type, ledger_source_id);

-- 6. Rule confidence model.
--    New rules default to 'review_first'; once confirmed_matches reaches
--    auto_post_after_n, the app promotes them to 'auto_post'.
ALTER TABLE bank_transaction_rules
    ADD COLUMN confidence_mode     TEXT    NOT NULL DEFAULT 'review_first';
ALTER TABLE bank_transaction_rules
    ADD COLUMN auto_post_after_n   INTEGER NOT NULL DEFAULT 3;
ALTER TABLE bank_transaction_rules
    ADD COLUMN confirmed_matches   INTEGER NOT NULL DEFAULT 0;

COMMIT;

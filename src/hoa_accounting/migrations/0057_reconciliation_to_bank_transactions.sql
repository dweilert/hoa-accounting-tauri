-- Migration 0057: Retarget reconciliation_clears at bank_transactions.
--
-- Reconciliation is moving from "clear this ledger record (payment,
-- income_batch, bill_payment, reserve_transfer)" to "clear this
-- bank_transaction row" — the bank line is the authoritative statement
-- that something cleared the account.
--
-- The ledger-record linkage survives through bank_transaction_links, so a
-- cleared bank_transaction still tells you which payment(s)/bill(s) it
-- represents. That de-duplicates reconciliation state (one bank line is
-- one clear, even if it represents a deposit batch of many payments).
--
-- This migration:
--   1. Wipes any existing clears (per user directive — the reconciliation
--      data built on the polymorphic model is short-lived and can be
--      re-finalized from scratch).
--   2. Drops reconciliation_clears and recreates it keyed by
--      bank_transaction_id, with a unique index on
--      (reconciliation_id, bank_transaction_id).
--
-- The old (source_type, source_id) polymorphic columns are gone. Code that
-- still references them has been updated in the same change set.

BEGIN TRANSACTION;

DELETE FROM reconciliation_clears;
DROP TABLE reconciliation_clears;

CREATE TABLE reconciliation_clears (
    id                    INTEGER PRIMARY KEY,
    reconciliation_id     INTEGER NOT NULL
        REFERENCES bank_reconciliations(id) ON DELETE CASCADE,
    bank_transaction_id   INTEGER NOT NULL
        REFERENCES bank_transactions(id) ON DELETE CASCADE,
    cleared_at            TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (reconciliation_id, bank_transaction_id)
);

CREATE INDEX idx_reconciliation_clears_recon
    ON reconciliation_clears(reconciliation_id);
CREATE INDEX idx_reconciliation_clears_bank_txn
    ON reconciliation_clears(bank_transaction_id);

COMMIT;

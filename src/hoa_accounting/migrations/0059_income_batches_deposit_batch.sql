-- Migration 0059: Tie income_batches to their deposit slip.
--
-- Deposits (deposit_batches) can now contain a mix of owner payments and
-- one-off non-owner income (e.g. insurance rebate, vendor refund) that
-- the treasurer aggregates into a single bank deposit. Adding the FK
-- lets the bank-import rule engine match one statement line to the full
-- slip total — member payments AND member income rows — the same way it
-- already does for pure owner-payment batches.
--
-- Nullable: existing income_batches rows pre-date the unified Record
-- Deposit flow and don't belong to a deposit batch. The new flow sets
-- the FK on every row it creates.

BEGIN TRANSACTION;

ALTER TABLE income_batches
    ADD COLUMN deposit_batch_id INTEGER
    REFERENCES deposit_batches(id) ON DELETE SET NULL;

CREATE INDEX idx_income_batches_deposit_batch
    ON income_batches(deposit_batch_id);

COMMIT;

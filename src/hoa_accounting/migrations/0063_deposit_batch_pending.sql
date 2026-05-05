-- Migration 0063: deposit_batches posting_status + deposit_batch_lines
--
-- Adds "always pending" support to the Record Deposit workflow:
--
--   posting_status = PENDING  ← saved by Record Deposit, not yet posted
--   posting_status = POSTED   ← payments/income_batches already materialized
--   posting_status = CANCELLED← voided before OFX confirmation
--
-- deposit_batch_lines captures per-check intent for PENDING batches so
-- Accept All can materialize the correct payment rows when the bank
-- confirms the deposit via OFX.
--
-- All existing batches are marked POSTED (they were already posted
-- immediately in the old flow).

BEGIN TRANSACTION;

ALTER TABLE deposit_batches
    ADD COLUMN posting_status TEXT NOT NULL DEFAULT 'POSTED'
        CHECK (posting_status IN ('PENDING', 'POSTED', 'CANCELLED'));

UPDATE deposit_batches SET posting_status = 'POSTED';

-- Per-check intent row for a pending deposit_batch.
-- One row per line the treasurer entered on the Record Deposit form.
-- For owner-payment rows:  lot_id IS NOT NULL, category_id = dues/fee cat
-- For non-owner income rows: lot_id IS NULL, category_id = income cat
CREATE TABLE deposit_batch_lines (
    id                       INTEGER PRIMARY KEY,
    deposit_batch_id         INTEGER NOT NULL REFERENCES deposit_batches(id),
    -- NULL for non-owner income rows
    lot_id                   INTEGER REFERENCES lots(id),
    -- Category that drives posting behavior.
    -- NULL for owner-payment rows (charge_type_filter drives posting there).
    category_id              INTEGER REFERENCES categories(id),
    amount                   NUMERIC NOT NULL,
    reference_number         TEXT,
    memo                     TEXT NOT NULL DEFAULT '',
    -- Comma-separated charge_type codes for regular owner-payment rows
    -- e.g. "DUES,LATE_FEE" or "RESALE_FEE"
    charge_type_filter       TEXT,
    -- Comma-separated assessment ids for specific-charges owner-payment rows
    apply_to_assessment_ids  TEXT
);

CREATE INDEX idx_deposit_batch_lines_batch
    ON deposit_batch_lines(deposit_batch_id);

COMMIT;

-- Migration 0067: Make deposit_batch_lines.category_id nullable.
--
-- Migration 0063 created the column as NOT NULL, but owner-payment lines
-- intentionally carry category_id = NULL — their posting is driven by
-- charge_type_filter (DUES / LATE_FEE / RESALE_FEE), not a GL category.
-- Only non-owner income lines carry a real category_id.

BEGIN TRANSACTION;

CREATE TABLE deposit_batch_lines_new (
    id                       INTEGER PRIMARY KEY,
    deposit_batch_id         INTEGER NOT NULL REFERENCES deposit_batches(id),
    -- NULL for non-owner income rows
    lot_id                   INTEGER REFERENCES lots(id),
    -- NULL for owner-payment rows; populated for non-owner income rows
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

INSERT INTO deposit_batch_lines_new
    SELECT id, deposit_batch_id, lot_id, category_id, amount,
           reference_number, memo, charge_type_filter, apply_to_assessment_ids
    FROM deposit_batch_lines;

DROP TABLE deposit_batch_lines;
ALTER TABLE deposit_batch_lines_new RENAME TO deposit_batch_lines;

CREATE INDEX idx_deposit_batch_lines_batch
    ON deposit_batch_lines(deposit_batch_id);

COMMIT;

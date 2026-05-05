-- Migration 0064: deferred Classify Transaction metadata
--
-- Adds columns so "Save Classification" in Classify Transaction can store
-- intent without immediately creating ledger records.  Accept All reads
-- these columns to post the actual records.
--
-- classify_type: OWNER_PAYMENT | INCOME | EXPENSE
-- classify_vendor_id: for EXPENSE rows
-- classify_lot_id: for OWNER_PAYMENT rows
-- classify_lines_json: JSON array of {category_id, amount} dicts for splits
--
-- All columns are NULL when the bank transaction was not manually classified.

BEGIN TRANSACTION;

ALTER TABLE bank_transactions ADD COLUMN classify_type TEXT;
ALTER TABLE bank_transactions ADD COLUMN classify_vendor_id INTEGER;
ALTER TABLE bank_transactions ADD COLUMN classify_lot_id INTEGER;
ALTER TABLE bank_transactions ADD COLUMN classify_lines_json TEXT;

COMMIT;

-- Migration 0009: Add statement beginning balance to bank_reconciliations
--
-- Stores the opening balance from the bank statement so it can be compared
-- against the prior reconciliation's book balance as a sanity check.

BEGIN TRANSACTION;

ALTER TABLE bank_reconciliations
    ADD COLUMN statement_beginning_balance NUMERIC;   -- nullable; NULL on existing rows

COMMIT;

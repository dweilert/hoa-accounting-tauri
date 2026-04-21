-- Migration 0043: Add optional lot_id to bank_transaction_rules
-- Allows a dues_payment rule to auto-record an AR payment for a specific lot.

ALTER TABLE bank_transaction_rules
    ADD COLUMN lot_id INTEGER REFERENCES lots(id);

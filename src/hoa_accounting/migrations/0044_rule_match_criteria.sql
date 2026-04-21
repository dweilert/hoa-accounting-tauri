-- Migration 0044: Add match_type, match_memo, match_amount to bank_transaction_rules.
-- All criteria are optional; non-empty values are ANDed together with description_contains.

ALTER TABLE bank_transaction_rules
    ADD COLUMN match_type   TEXT NOT NULL DEFAULT '';

ALTER TABLE bank_transaction_rules
    ADD COLUMN match_memo   TEXT NOT NULL DEFAULT '';

ALTER TABLE bank_transaction_rules
    ADD COLUMN match_amount TEXT NOT NULL DEFAULT '';

-- Migration 0045: Add optional bank_account_id to bank_transaction_rules.
-- When set, the rule only fires when importing from that specific bank account.

ALTER TABLE bank_transaction_rules
    ADD COLUMN bank_account_id INTEGER REFERENCES bank_accounts(id);

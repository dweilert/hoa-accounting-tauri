-- Migration 0046: Enforce unique rule names in bank_transaction_rules.
CREATE UNIQUE INDEX IF NOT EXISTS idx_bank_transaction_rules_name
    ON bank_transaction_rules (rule_name);

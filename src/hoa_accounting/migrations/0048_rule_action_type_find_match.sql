-- Migration 0048: Expand action_type CHECK to include homeowner_batch and vendor_bill_match.

PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;

CREATE TABLE bank_transaction_rules_new (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name            TEXT    NOT NULL,
    description_contains TEXT    NOT NULL DEFAULT '',
    action_type          TEXT    NOT NULL DEFAULT 'recurring_bill'
                             CHECK (action_type IN (
                                 'recurring_bill',
                                 'dues_payment',
                                 'fee_income',
                                 'bank_charge',
                                 'direct_expense',
                                 'direct_income',
                                 'homeowner_batch',
                                 'vendor_bill_match'
                             )),
    gl_account_id        INTEGER REFERENCES accounts(id),
    default_memo         TEXT    NOT NULL DEFAULT '',
    active_flag          INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    created_at           TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lot_id               INTEGER REFERENCES lots(id),
    match_type           TEXT    NOT NULL DEFAULT '',
    match_memo           TEXT    NOT NULL DEFAULT '',
    match_amount         TEXT    NOT NULL DEFAULT '',
    bank_account_id      INTEGER REFERENCES bank_accounts(id)
);

INSERT INTO bank_transaction_rules_new
    SELECT id, rule_name, description_contains, action_type,
           gl_account_id, default_memo, active_flag, created_at,
           lot_id, match_type, match_memo, match_amount, bank_account_id
    FROM bank_transaction_rules;

DROP TABLE bank_transaction_rules;
ALTER TABLE bank_transaction_rules_new RENAME TO bank_transaction_rules;

CREATE UNIQUE INDEX idx_bank_transaction_rules_name ON bank_transaction_rules (rule_name);

COMMIT;
PRAGMA foreign_keys = ON;

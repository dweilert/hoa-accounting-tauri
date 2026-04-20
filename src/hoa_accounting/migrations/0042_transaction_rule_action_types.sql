-- Migration 0042: Expand bank_transaction_rules.action_type CHECK constraint
-- to support plain-English HOA action types.

BEGIN TRANSACTION;

-- SQLite can't ALTER a CHECK constraint, so recreate the table.
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
                                 'direct_income'
                             )),
    gl_account_id        INTEGER REFERENCES accounts(id),
    default_memo         TEXT    NOT NULL DEFAULT '',
    active_flag          INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    created_at           TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO bank_transaction_rules_new
    SELECT id, rule_name, description_contains, action_type,
           gl_account_id, default_memo, active_flag, created_at
    FROM bank_transaction_rules;

DROP TABLE bank_transaction_rules;
ALTER TABLE bank_transaction_rules_new RENAME TO bank_transaction_rules;

COMMIT;

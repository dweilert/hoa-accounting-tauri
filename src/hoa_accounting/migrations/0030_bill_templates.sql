-- Recurring vendor bill templates for one-click pre-fill on the bill entry form.
CREATE TABLE IF NOT EXISTS bill_templates (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    template_name           TEXT    NOT NULL,
    vendor_id               INTEGER NOT NULL REFERENCES vendors(id),
    expense_account_id      INTEGER NOT NULL REFERENCES accounts(id),
    payable_account_id      INTEGER NOT NULL REFERENCES accounts(id),
    fund_code               TEXT    NOT NULL DEFAULT 'OPERATING',
    expense_classification  TEXT    NOT NULL DEFAULT 'OPERATING',
    default_amount          TEXT,
    description             TEXT,
    active_flag             INTEGER NOT NULL DEFAULT 1,
    created_at              TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT    NOT NULL DEFAULT (datetime('now'))
);

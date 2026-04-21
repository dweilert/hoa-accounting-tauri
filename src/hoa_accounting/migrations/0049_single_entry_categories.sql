-- Migration 0049: Single-entry conversion — categories table + nullable journal_entry_id.
--
-- Adds a flat categories table (replaces chart-of-accounts for labeling income
-- and expenses). Seeds 17 starter categories. Adds category_id FK columns to
-- the core transaction tables. Rebuilds seven tables to make journal_entry_id
-- nullable so services no longer need to post a journal entry before inserting.
--
-- The migrator sets PRAGMA foreign_keys = OFF before running this script so
-- the table-swap pattern (rename → create → insert-select → drop) is safe.

BEGIN TRANSACTION;

-- ── 1. Categories table ────────────────────────────────────────────────────

CREATE TABLE categories (
    id            INTEGER PRIMARY KEY,
    code          TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    category_type TEXT    NOT NULL
                      CHECK (category_type IN ('INCOME', 'EXPENSE', 'TRANSFER')),
    fund_code     TEXT    NOT NULL DEFAULT 'OPERATING'
                      CHECK (fund_code IN ('OPERATING', 'RESERVE', 'SPECIAL')),
    sort_order    INTEGER NOT NULL DEFAULT 0,
    active_flag   INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ── 2. Seed default categories ─────────────────────────────────────────────

INSERT INTO categories (code, name, category_type, fund_code, sort_order) VALUES
    ('DUES',             'HOA Dues',                    'INCOME',   'OPERATING', 10),
    ('LATE_FEE',         'Late Payment Fees',            'INCOME',   'OPERATING', 20),
    ('RESALE_FEE',       'Resale / Transfer Fees',       'INCOME',   'OPERATING', 30),
    ('BANK_INTEREST',    'Bank Interest',                'INCOME',   'OPERATING', 40),
    ('RESERVE_INTEREST', 'Reserve Fund Interest',        'INCOME',   'RESERVE',   45),
    ('OTHER_INCOME',     'Other Income',                 'INCOME',   'OPERATING', 50),
    ('LANDSCAPING',      'Landscaping & Grounds',        'EXPENSE',  'OPERATING', 110),
    ('UTILITIES',        'Utilities',                    'EXPENSE',  'OPERATING', 120),
    ('INSURANCE',        'Insurance',                    'EXPENSE',  'OPERATING', 130),
    ('MANAGEMENT',       'Management Fees',              'EXPENSE',  'OPERATING', 140),
    ('LEGAL',            'Legal & Professional',         'EXPENSE',  'OPERATING', 150),
    ('REPAIRS',          'Repairs & Maintenance',        'EXPENSE',  'OPERATING', 160),
    ('ADMIN',            'Administrative',               'EXPENSE',  'OPERATING', 170),
    ('TAXES',            'Taxes & Government Fees',      'EXPENSE',  'OPERATING', 180),
    ('OTHER_EXPENSE',    'Other Expenses',               'EXPENSE',  'OPERATING', 190),
    ('RESERVE_EXPENSE',  'Reserve Fund Expenditures',    'EXPENSE',  'RESERVE',   210),
    ('RESERVE_TRANSFER', 'Reserve Fund Contribution',    'TRANSFER', 'OPERATING', 310);

-- ── 3. Add category_id to core transaction tables (nullable, no default) ───

ALTER TABLE assessments        ADD COLUMN category_id INTEGER REFERENCES categories(id);
ALTER TABLE payments           ADD COLUMN category_id INTEGER REFERENCES categories(id);
ALTER TABLE deposit_batches    ADD COLUMN category_id INTEGER REFERENCES categories(id);
ALTER TABLE vendor_bills       ADD COLUMN category_id INTEGER REFERENCES categories(id);
ALTER TABLE bill_payments      ADD COLUMN category_id INTEGER REFERENCES categories(id);
ALTER TABLE income_batches     ADD COLUMN category_id INTEGER REFERENCES categories(id);
ALTER TABLE reserve_transfers  ADD COLUMN category_id INTEGER REFERENCES categories(id);
ALTER TABLE owner_adjustments  ADD COLUMN category_id INTEGER REFERENCES categories(id);

-- ── 4. Rebuild tables to make journal_entry_id nullable ───────────────────
--
-- SQLite cannot ALTER COLUMN, so we use the rename→create→insert→drop pattern.
-- PRAGMA foreign_keys is OFF (set by the migrator) so FK checks don't fire
-- while intermediate table names are live.

-- ── 4a. assessments ────────────────────────────────────────────────────────

ALTER TABLE assessments RENAME TO _assessments_old_0049;

CREATE TABLE assessments (
    id                  INTEGER PRIMARY KEY,
    lot_id              INTEGER NOT NULL,
    owner_id            INTEGER NOT NULL,
    assessment_rule_id  INTEGER,
    assessment_date     TEXT    NOT NULL,
    due_date            TEXT    NOT NULL,
    amount              NUMERIC NOT NULL,
    description         TEXT    NOT NULL,
    status              TEXT    NOT NULL DEFAULT 'OPEN'
                            CHECK (status IN ('OPEN','PARTIAL','PAID','VOID','WRITTEN_OFF')),
    journal_entry_id    INTEGER,
    category_id         INTEGER REFERENCES categories(id),
    charge_type         TEXT    NOT NULL DEFAULT 'DUES',
    created_at          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lot_id)             REFERENCES lots(id),
    FOREIGN KEY (owner_id)           REFERENCES owners(id),
    FOREIGN KEY (assessment_rule_id) REFERENCES assessment_rules(id),
    CHECK (amount >= 0)
);

INSERT INTO assessments
    (id, lot_id, owner_id, assessment_rule_id, assessment_date, due_date,
     amount, description, status, journal_entry_id, charge_type, created_at, updated_at)
SELECT id, lot_id, owner_id, assessment_rule_id, assessment_date, due_date,
       amount, description, status, journal_entry_id, charge_type, created_at, updated_at
FROM _assessments_old_0049;

DROP TABLE _assessments_old_0049;

-- ── 4b. payments ───────────────────────────────────────────────────────────

ALTER TABLE payments RENAME TO _payments_old_0049;

CREATE TABLE payments (
    id               INTEGER PRIMARY KEY,
    receipt_number   TEXT    NOT NULL UNIQUE,
    owner_id         INTEGER NOT NULL,
    payment_date     TEXT    NOT NULL,
    amount           NUMERIC NOT NULL,
    payment_method   TEXT    NOT NULL
                         CHECK (payment_method IN ('CHECK','ACH','CASH','CARD','OTHER')),
    reference_number TEXT,
    bank_account_id  INTEGER NOT NULL,
    journal_entry_id INTEGER,
    notes            TEXT,
    deposit_batch_id INTEGER,
    category_id      INTEGER REFERENCES categories(id),
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id)        REFERENCES owners(id),
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id),
    CHECK (amount > 0)
);

INSERT INTO payments
    (id, receipt_number, owner_id, payment_date, amount, payment_method,
     reference_number, bank_account_id, journal_entry_id, notes, deposit_batch_id, created_at)
SELECT id, receipt_number, owner_id, payment_date, amount, payment_method,
       reference_number, bank_account_id, journal_entry_id, notes, deposit_batch_id, created_at
FROM _payments_old_0049;

DROP TABLE _payments_old_0049;

CREATE INDEX IF NOT EXISTS idx_payments_owner_id     ON payments(owner_id);
CREATE INDEX IF NOT EXISTS idx_payments_deposit_batch ON payments(deposit_batch_id);

-- ── 4c. deposit_batches ────────────────────────────────────────────────────

ALTER TABLE deposit_batches RENAME TO _deposit_batches_old_0049;

CREATE TABLE deposit_batches (
    id               INTEGER PRIMARY KEY,
    deposit_date     TEXT    NOT NULL,
    bank_account_id  INTEGER NOT NULL,
    journal_entry_id INTEGER,
    total_amount     NUMERIC NOT NULL,
    notes            TEXT,
    created_by_user_id INTEGER,
    category_id      INTEGER REFERENCES categories(id),
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bank_account_id)    REFERENCES bank_accounts(id),
    FOREIGN KEY (created_by_user_id) REFERENCES users(id),
    CHECK (total_amount > 0)
);

INSERT INTO deposit_batches
    (id, deposit_date, bank_account_id, journal_entry_id, total_amount,
     notes, created_by_user_id, created_at)
SELECT id, deposit_date, bank_account_id, journal_entry_id, total_amount,
       notes, created_by_user_id, created_at
FROM _deposit_batches_old_0049;

DROP TABLE _deposit_batches_old_0049;

CREATE INDEX IF NOT EXISTS idx_deposit_batches_date ON deposit_batches(deposit_date);
CREATE INDEX IF NOT EXISTS idx_deposit_batches_bank ON deposit_batches(bank_account_id);

-- ── 4d. vendor_bills ───────────────────────────────────────────────────────

ALTER TABLE vendor_bills RENAME TO _vendor_bills_old_0049;

CREATE TABLE vendor_bills (
    id                  INTEGER PRIMARY KEY,
    vendor_id           INTEGER NOT NULL,
    invoice_number      TEXT    NOT NULL,
    invoice_date        TEXT    NOT NULL,
    due_date            TEXT,
    amount              NUMERIC NOT NULL,
    expense_account_id  INTEGER,
    payable_account_id  INTEGER,
    fund_code           TEXT    NOT NULL DEFAULT 'OPERATING'
                            CHECK (fund_code IN ('OPERATING','RESERVE','SPECIAL')),
    status              TEXT    NOT NULL DEFAULT 'OPEN'
                            CHECK (status IN ('OPEN','PARTIAL','PAID','VOID')),
    journal_entry_id    INTEGER,
    description         TEXT,
    category_id         INTEGER REFERENCES categories(id),
    created_at          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES vendors(id),
    UNIQUE (vendor_id, invoice_number),
    CHECK (amount >= 0)
);

INSERT INTO vendor_bills
    (id, vendor_id, invoice_number, invoice_date, due_date, amount,
     expense_account_id, payable_account_id, fund_code, status,
     journal_entry_id, description, created_at, updated_at)
SELECT id, vendor_id, invoice_number, invoice_date, due_date, amount,
       expense_account_id, payable_account_id, fund_code, status,
       journal_entry_id, description, created_at, updated_at
FROM _vendor_bills_old_0049;

DROP TABLE _vendor_bills_old_0049;

-- ── 4e. bill_payments ─────────────────────────────────────────────────────

ALTER TABLE bill_payments RENAME TO _bill_payments_old_0049;

CREATE TABLE bill_payments (
    id               INTEGER PRIMARY KEY,
    vendor_bill_id   INTEGER NOT NULL,
    payment_date     TEXT    NOT NULL,
    amount           NUMERIC NOT NULL,
    bank_account_id  INTEGER NOT NULL,
    check_number     TEXT,
    journal_entry_id INTEGER,
    notes            TEXT,
    category_id      INTEGER REFERENCES categories(id),
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_bill_id)  REFERENCES vendor_bills(id),
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id),
    CHECK (amount > 0)
);

INSERT INTO bill_payments
    (id, vendor_bill_id, payment_date, amount, bank_account_id,
     check_number, journal_entry_id, notes, created_at)
SELECT id, vendor_bill_id, payment_date, amount, bank_account_id,
       check_number, journal_entry_id, notes, created_at
FROM _bill_payments_old_0049;

DROP TABLE _bill_payments_old_0049;

-- ── 4f. income_batches ─────────────────────────────────────────────────────

ALTER TABLE income_batches RENAME TO _income_batches_old_0049;

CREATE TABLE income_batches (
    id                  INTEGER PRIMARY KEY,
    posting_date        TEXT    NOT NULL,
    bank_account_id     INTEGER NOT NULL,
    income_account_id   INTEGER,
    income_description  TEXT    NOT NULL,
    total_amount        NUMERIC NOT NULL,
    notes               TEXT,
    journal_entry_id    INTEGER,
    created_by_user_id  INTEGER,
    category_id         INTEGER REFERENCES categories(id),
    created_at          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bank_account_id)    REFERENCES bank_accounts(id),
    FOREIGN KEY (created_by_user_id) REFERENCES users(id),
    CHECK (total_amount > 0)
);

INSERT INTO income_batches
    (id, posting_date, bank_account_id, income_account_id, income_description,
     total_amount, notes, journal_entry_id, created_by_user_id, created_at)
SELECT id, posting_date, bank_account_id, income_account_id, income_description,
       total_amount, notes, journal_entry_id, created_by_user_id, created_at
FROM _income_batches_old_0049;

DROP TABLE _income_batches_old_0049;

CREATE INDEX IF NOT EXISTS idx_income_batches_date    ON income_batches(posting_date);
CREATE INDEX IF NOT EXISTS idx_income_batches_account ON income_batches(income_account_id);

-- ── 4g. reserve_transfers ──────────────────────────────────────────────────

ALTER TABLE reserve_transfers RENAME TO _reserve_transfers_old_0049;

CREATE TABLE reserve_transfers (
    id               INTEGER PRIMARY KEY,
    transfer_date    TEXT    NOT NULL,
    from_account_id  INTEGER NOT NULL,
    to_account_id    INTEGER NOT NULL,
    amount           NUMERIC NOT NULL,
    journal_entry_id INTEGER,
    notes            TEXT,
    transfer_type    TEXT,
    purpose          TEXT,
    category_id      INTEGER REFERENCES categories(id),
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_account_id) REFERENCES accounts(id),
    FOREIGN KEY (to_account_id)   REFERENCES accounts(id),
    CHECK (amount > 0),
    CHECK (from_account_id <> to_account_id)
);

INSERT INTO reserve_transfers
    (id, transfer_date, from_account_id, to_account_id, amount,
     journal_entry_id, notes, transfer_type, purpose, created_at)
SELECT id, transfer_date, from_account_id, to_account_id, amount,
       journal_entry_id, notes, transfer_type, purpose, created_at
FROM _reserve_transfers_old_0049;

DROP TABLE _reserve_transfers_old_0049;

-- ── 4h. owner_adjustments ─────────────────────────────────────────────────

ALTER TABLE owner_adjustments RENAME TO _owner_adj_old_0049;

CREATE TABLE owner_adjustments (
    id               INTEGER PRIMARY KEY,
    owner_id         INTEGER NOT NULL,
    lot_id           INTEGER NOT NULL,
    adjustment_type  TEXT    NOT NULL
                         CHECK (adjustment_type IN ('LATE_FEE','CREDIT_MEMO','WRITE_OFF','OTHER')),
    adjustment_date  TEXT    NOT NULL,
    amount           NUMERIC NOT NULL,
    description      TEXT    NOT NULL,
    journal_entry_id INTEGER,
    category_id      INTEGER REFERENCES categories(id),
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES owners(id),
    FOREIGN KEY (lot_id)   REFERENCES lots(id),
    CHECK (amount > 0)
);

INSERT INTO owner_adjustments
    (id, owner_id, lot_id, adjustment_type, adjustment_date,
     amount, description, journal_entry_id, created_at)
SELECT id, owner_id, lot_id, adjustment_type, adjustment_date,
       amount, description, journal_entry_id, created_at
FROM _owner_adj_old_0049;

DROP TABLE _owner_adj_old_0049;

COMMIT;

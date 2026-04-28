-- Migration 0061: Remove Chart of Accounts + journal-entry tables.
--
-- For a single-entry cash-basis HOA, the GL accounts model is redundant
-- with categories + bank_accounts. This migration:
--
--   1. Drops dead tables: accounts, account_types, journal_entries,
--      journal_entry_lines, fiscal_year_closes, wizard_option_accounts.
--   2. Rebuilds tables that had UNIQUE or FK columns we need to drop
--      (SQLite restricts DROP COLUMN on those).
--   3. Drops simpler dead columns from remaining tables.
--
-- This migration assumes a fresh DB or one where transactional data has
-- been wiped — there is no per-row data preservation.

PRAGMA foreign_keys = OFF;

------------------------------------------------------------
-- 0. Wipe all transactional and master data (keep categories only)
------------------------------------------------------------

DELETE FROM bank_transaction_rules;
DELETE FROM bank_import_batches;
DELETE FROM bank_import_stash;
DELETE FROM bank_transaction_links;
DELETE FROM bank_account_file_formats;
DELETE FROM bank_reconciliation_lines;
DELETE FROM reconciliation_clears;
DELETE FROM bank_reconciliations;
DELETE FROM payment_applications;
DELETE FROM payments;
DELETE FROM bill_payments;
DELETE FROM vendor_bills;
DELETE FROM income_batches;
DELETE FROM deposit_batches;
DELETE FROM owner_adjustments;
DELETE FROM dues_billing_history;
DELETE FROM assessments;
DELETE FROM bill_templates;
DELETE FROM lot_renters;
DELETE FROM lot_ownership;
DELETE FROM lots;
DELETE FROM owners;
DELETE FROM vendors;
DELETE FROM board_members;
DELETE FROM budget_lines;
DELETE FROM budgets;
DELETE FROM opening_balances;
DELETE FROM reserve_assets;
DELETE FROM reserve_components;
DELETE FROM reserve_study_assumptions;
DELETE FROM reserve_study_scenarios;
DELETE FROM accounting_periods;
DELETE FROM audit_log;
DELETE FROM dashboard_alert_dismissals;

------------------------------------------------------------
-- 1. Rebuild bank_accounts: drop gl_account_id (UNIQUE+FK), add fund_code
------------------------------------------------------------

DROP TABLE IF EXISTS bank_accounts__new;
CREATE TABLE bank_accounts__new (
    id INTEGER PRIMARY KEY,
    account_name TEXT NOT NULL,
    institution_name TEXT NOT NULL,
    account_last4 TEXT,
    account_type TEXT NOT NULL
        CHECK (account_type IN ('CHECKING', 'SAVINGS', 'MONEY_MARKET', 'OTHER')),
    fund_code TEXT NOT NULL DEFAULT 'OPERATING'
        CHECK (fund_code IN ('OPERATING','RESERVE','SPECIAL')),
    active_flag INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    opening_balance NUMERIC NOT NULL DEFAULT 0,
    opening_balance_date TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Data was wiped in step 0; no rows to copy.
DROP TABLE bank_accounts;
ALTER TABLE bank_accounts__new RENAME TO bank_accounts;

------------------------------------------------------------
-- 2. Rebuild assessment_rules: drop FK cols, add category_id
------------------------------------------------------------

DROP TABLE IF EXISTS assessment_rules__new;
CREATE TABLE assessment_rules__new (
    id INTEGER PRIMARY KEY,
    rule_name TEXT NOT NULL,
    frequency TEXT NOT NULL
        CHECK (frequency IN ('ANNUAL','SEMIANNUAL','QUARTERLY','MONTHLY','CUSTOM')),
    default_amount NUMERIC NOT NULL,
    category_id INTEGER REFERENCES categories(id),
    fund_code TEXT NOT NULL DEFAULT 'OPERATING'
        CHECK (fund_code IN ('OPERATING','RESERVE','SPECIAL')),
    effective_start_date TEXT NOT NULL,
    effective_end_date TEXT,
    active_flag INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    notes TEXT,
    CHECK (default_amount >= 0),
    CHECK (effective_end_date IS NULL OR effective_end_date >= effective_start_date)
);
-- Data was wiped in step 0; no rows to copy.
DROP TABLE assessment_rules;
ALTER TABLE assessment_rules__new RENAME TO assessment_rules;

------------------------------------------------------------
-- 3. Rebuild reserve_transfers: drop FK cols, add bank_account FKs
------------------------------------------------------------

DROP TABLE IF EXISTS reserve_transfers__new;
CREATE TABLE reserve_transfers__new (
    id INTEGER PRIMARY KEY,
    transfer_date TEXT NOT NULL,
    from_bank_account_id INTEGER REFERENCES bank_accounts(id),
    to_bank_account_id   INTEGER REFERENCES bank_accounts(id),
    amount NUMERIC NOT NULL,
    notes TEXT,
    transfer_type TEXT,
    purpose TEXT,
    category_id INTEGER REFERENCES categories(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
DROP TABLE reserve_transfers;
ALTER TABLE reserve_transfers__new RENAME TO reserve_transfers;

------------------------------------------------------------
-- 4. Rebuild bank_transactions: drop JE-related FK columns
------------------------------------------------------------

DROP TABLE IF EXISTS bank_transactions__new;
CREATE TABLE bank_transactions__new (
    id INTEGER PRIMARY KEY,
    bank_account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
    import_batch_id INTEGER,
    transaction_date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    external_reference TEXT,
    reconciliation_status TEXT NOT NULL DEFAULT 'UNMATCHED'
        CHECK (reconciliation_status IN ('UNMATCHED','MATCHED','CLEARED')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    memo TEXT NOT NULL DEFAULT '',
    transaction_type TEXT NOT NULL DEFAULT '',
    match_type TEXT NOT NULL DEFAULT 'UNMATCHED',
    batch_match_ids TEXT NOT NULL DEFAULT '[]',
    rule_id INTEGER REFERENCES bank_transaction_rules(id),
    matched_payment_ids TEXT NOT NULL DEFAULT '[]',
    matched_bill_ids    TEXT NOT NULL DEFAULT '[]',
    category_id INTEGER REFERENCES categories(id),
    matched_source_type TEXT,
    matched_source_id INTEGER,
    dedup_key TEXT NOT NULL DEFAULT '',
    validation_status TEXT NOT NULL DEFAULT 'UNVALIDATED'
);
DROP TABLE bank_transactions;
ALTER TABLE bank_transactions__new RENAME TO bank_transactions;
CREATE INDEX idx_bank_transactions_bank_account_date ON bank_transactions(bank_account_id, transaction_date);
CREATE UNIQUE INDEX idx_bank_transactions_dedup ON bank_transactions(bank_account_id, dedup_key);
CREATE INDEX idx_bank_transactions_validation ON bank_transactions(validation_status, bank_account_id, transaction_date);

------------------------------------------------------------
-- 5. Simple drop-columns on tables that don't have UNIQUE/FK on the cols
------------------------------------------------------------

ALTER TABLE vendor_bills           DROP COLUMN expense_account_id;
ALTER TABLE bank_transaction_rules DROP COLUMN gl_account_id;
ALTER TABLE bill_templates         DROP COLUMN expense_account_id;
ALTER TABLE bill_templates         DROP COLUMN payable_account_id;

ALTER TABLE assessments       DROP COLUMN journal_entry_id;
ALTER TABLE payments          DROP COLUMN journal_entry_id;
ALTER TABLE vendor_bills      DROP COLUMN journal_entry_id;
ALTER TABLE bill_payments     DROP COLUMN journal_entry_id;
ALTER TABLE deposit_batches   DROP COLUMN journal_entry_id;
ALTER TABLE income_batches    DROP COLUMN journal_entry_id;
ALTER TABLE opening_balances  DROP COLUMN journal_entry_id;
ALTER TABLE owner_adjustments DROP COLUMN journal_entry_id;

DELETE FROM opening_balances WHERE entity_type = 'account';
ALTER TABLE opening_balances ADD COLUMN bank_account_id INTEGER REFERENCES bank_accounts(id);

------------------------------------------------------------
-- 6. Drop dead tables
------------------------------------------------------------

DROP TABLE IF EXISTS wizard_option_accounts;
DROP TABLE IF EXISTS journal_entry_lines;
DROP TABLE IF EXISTS journal_entries;
DROP TABLE IF EXISTS fiscal_year_closes;
DROP TABLE IF EXISTS accounts;
DROP TABLE IF EXISTS account_types;

PRAGMA foreign_keys = ON;

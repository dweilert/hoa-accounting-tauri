
PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS hoa_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    legal_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    corporate_state TEXT,
    federal_tax_id TEXT,
    state_tax_id TEXT,
    formation_date TEXT,
    mailing_address_1 TEXT,
    mailing_address_2 TEXT,
    city TEXT,
    state TEXT,
    postal_code TEXT,
    phone TEXT,
    email TEXT,
    website TEXT,
    fiscal_year_start_month INTEGER NOT NULL DEFAULT 1
        CHECK (fiscal_year_start_month BETWEEN 1 AND 12),
    timezone TEXT NOT NULL DEFAULT 'America/Chicago',
    default_currency TEXT NOT NULL DEFAULT 'USD',
    logo_path TEXT,
    report_header_text TEXT,
    report_footer_text TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    last_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY,
    role_code TEXT NOT NULL UNIQUE,
    role_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_roles (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    role_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
    UNIQUE (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS board_members (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    title TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    start_date TEXT,
    end_date TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    notes TEXT
);

CREATE TABLE IF NOT EXISTS lots (
    id INTEGER PRIMARY KEY,
    lot_number TEXT NOT NULL UNIQUE,
    street_address_1 TEXT,
    street_address_2 TEXT,
    city TEXT,
    state TEXT,
    postal_code TEXT,
    legal_description TEXT,
    active_flag INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS owners (
    id INTEGER PRIMARY KEY,
    owner_type TEXT NOT NULL DEFAULT 'PERSON'
        CHECK (owner_type IN ('PERSON', 'ENTITY', 'TRUST')),
    display_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    entity_name TEXT,
    mailing_address_1 TEXT,
    mailing_address_2 TEXT,
    city TEXT,
    state TEXT,
    postal_code TEXT,
    phone TEXT,
    email TEXT,
    notes TEXT,
    active_flag INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lot_ownership (
    id INTEGER PRIMARY KEY,
    lot_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    ownership_percent NUMERIC NOT NULL DEFAULT 100.0,
    is_primary_contact INTEGER NOT NULL DEFAULT 1 CHECK (is_primary_contact IN (0, 1)),
    FOREIGN KEY (lot_id) REFERENCES lots(id),
    FOREIGN KEY (owner_id) REFERENCES owners(id),
    CHECK (ownership_percent > 0 AND ownership_percent <= 100)
);

CREATE TABLE IF NOT EXISTS account_types (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    normal_balance TEXT NOT NULL CHECK (normal_balance IN ('DEBIT', 'CREDIT')),
    financial_statement_group TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    account_number TEXT NOT NULL UNIQUE,
    account_name TEXT NOT NULL,
    account_type_id INTEGER NOT NULL,
    fund_code TEXT NOT NULL DEFAULT 'OPERATING'
        CHECK (fund_code IN ('OPERATING', 'RESERVE', 'SPECIAL')),
    is_bank_account INTEGER NOT NULL DEFAULT 0 CHECK (is_bank_account IN (0, 1)),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_type_id) REFERENCES account_types(id)
);

CREATE TABLE IF NOT EXISTS accounting_periods (
    id INTEGER PRIMARY KEY,
    period_name TEXT NOT NULL UNIQUE,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    fiscal_period INTEGER NOT NULL,
    is_closed INTEGER NOT NULL DEFAULT 0 CHECK (is_closed IN (0, 1)),
    closed_at TEXT,
    closed_by_user_id INTEGER,
    FOREIGN KEY (closed_by_user_id) REFERENCES users(id),
    CHECK (fiscal_period BETWEEN 1 AND 12),
    CHECK (start_date <= end_date)
);

CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY,
    vendor_name TEXT NOT NULL,
    contact_name TEXT,
    email TEXT,
    phone TEXT,
    address_1 TEXT,
    address_2 TEXT,
    city TEXT,
    state TEXT,
    postal_code TEXT,
    notes TEXT,
    active_flag INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bank_accounts (
    id INTEGER PRIMARY KEY,
    account_name TEXT NOT NULL,
    institution_name TEXT NOT NULL,
    account_last4 TEXT,
    account_type TEXT NOT NULL
        CHECK (account_type IN ('CHECKING', 'SAVINGS', 'MONEY_MARKET', 'OTHER')),
    gl_account_id INTEGER NOT NULL UNIQUE,
    active_flag INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (gl_account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY,
    entry_number TEXT NOT NULL UNIQUE,
    entry_date TEXT NOT NULL,
    accounting_period_id INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    source_id INTEGER,
    memo TEXT,
    status TEXT NOT NULL DEFAULT 'POSTED'
        CHECK (status IN ('DRAFT', 'POSTED', 'REVERSED')),
    reversal_entry_id INTEGER,
    created_by_user_id INTEGER,
    approved_by_user_id INTEGER,
    posted_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (accounting_period_id) REFERENCES accounting_periods(id),
    FOREIGN KEY (reversal_entry_id) REFERENCES journal_entries(id),
    FOREIGN KEY (created_by_user_id) REFERENCES users(id),
    FOREIGN KEY (approved_by_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS journal_entry_lines (
    id INTEGER PRIMARY KEY,
    journal_entry_id INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    lot_id INTEGER,
    owner_id INTEGER,
    vendor_id INTEGER,
    description TEXT,
    debit_amount NUMERIC NOT NULL DEFAULT 0,
    credit_amount NUMERIC NOT NULL DEFAULT 0,
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (lot_id) REFERENCES lots(id),
    FOREIGN KEY (owner_id) REFERENCES owners(id),
    FOREIGN KEY (vendor_id) REFERENCES vendors(id),
    UNIQUE (journal_entry_id, line_number),
    CHECK (debit_amount >= 0),
    CHECK (credit_amount >= 0),
    CHECK (
        (debit_amount > 0 AND credit_amount = 0)
        OR
        (credit_amount > 0 AND debit_amount = 0)
    )
);

CREATE TABLE IF NOT EXISTS assessment_rules (
    id INTEGER PRIMARY KEY,
    rule_name TEXT NOT NULL,
    frequency TEXT NOT NULL
        CHECK (frequency IN ('ANNUAL', 'SEMIANNUAL', 'QUARTERLY', 'MONTHLY', 'CUSTOM')),
    default_amount NUMERIC NOT NULL,
    income_account_id INTEGER NOT NULL,
    receivable_account_id INTEGER NOT NULL,
    effective_start_date TEXT NOT NULL,
    effective_end_date TEXT,
    fund_code TEXT NOT NULL DEFAULT 'OPERATING'
        CHECK (fund_code IN ('OPERATING', 'RESERVE', 'SPECIAL')),
    active_flag INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    notes TEXT,
    FOREIGN KEY (income_account_id) REFERENCES accounts(id),
    FOREIGN KEY (receivable_account_id) REFERENCES accounts(id),
    CHECK (default_amount >= 0),
    CHECK (effective_end_date IS NULL OR effective_end_date >= effective_start_date)
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY,
    lot_id INTEGER NOT NULL,
    owner_id INTEGER NOT NULL,
    assessment_rule_id INTEGER,
    assessment_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'PARTIAL', 'PAID', 'VOID', 'WRITTEN_OFF')),
    journal_entry_id INTEGER NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lot_id) REFERENCES lots(id),
    FOREIGN KEY (owner_id) REFERENCES owners(id),
    FOREIGN KEY (assessment_rule_id) REFERENCES assessment_rules(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id),
    CHECK (amount >= 0)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY,
    receipt_number TEXT NOT NULL UNIQUE,
    owner_id INTEGER NOT NULL,
    payment_date TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    payment_method TEXT NOT NULL
        CHECK (payment_method IN ('CHECK', 'ACH', 'CASH', 'CARD', 'OTHER')),
    reference_number TEXT,
    bank_account_id INTEGER NOT NULL,
    journal_entry_id INTEGER NOT NULL UNIQUE,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES owners(id),
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id),
    CHECK (amount > 0)
);

CREATE TABLE IF NOT EXISTS payment_applications (
    id INTEGER PRIMARY KEY,
    payment_id INTEGER NOT NULL,
    assessment_id INTEGER NOT NULL,
    applied_amount NUMERIC NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (payment_id) REFERENCES payments(id) ON DELETE CASCADE,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id),
    UNIQUE (payment_id, assessment_id),
    CHECK (applied_amount > 0)
);

CREATE TABLE IF NOT EXISTS owner_adjustments (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL,
    lot_id INTEGER NOT NULL,
    adjustment_type TEXT NOT NULL
        CHECK (adjustment_type IN ('LATE_FEE', 'CREDIT_MEMO', 'WRITE_OFF', 'OTHER')),
    adjustment_date TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    description TEXT NOT NULL,
    journal_entry_id INTEGER NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES owners(id),
    FOREIGN KEY (lot_id) REFERENCES lots(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id),
    CHECK (amount > 0)
);

CREATE TABLE IF NOT EXISTS vendor_bills (
    id INTEGER PRIMARY KEY,
    vendor_id INTEGER NOT NULL,
    invoice_number TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    due_date TEXT,
    amount NUMERIC NOT NULL,
    expense_account_id INTEGER NOT NULL,
    payable_account_id INTEGER NOT NULL,
    fund_code TEXT NOT NULL DEFAULT 'OPERATING'
        CHECK (fund_code IN ('OPERATING', 'RESERVE', 'SPECIAL')),
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'PARTIAL', 'PAID', 'VOID')),
    journal_entry_id INTEGER NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES vendors(id),
    FOREIGN KEY (expense_account_id) REFERENCES accounts(id),
    FOREIGN KEY (payable_account_id) REFERENCES accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id),
    UNIQUE (vendor_id, invoice_number),
    CHECK (amount >= 0)
);

CREATE TABLE IF NOT EXISTS bill_payments (
    id INTEGER PRIMARY KEY,
    vendor_bill_id INTEGER NOT NULL,
    payment_date TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    bank_account_id INTEGER NOT NULL,
    check_number TEXT,
    journal_entry_id INTEGER NOT NULL UNIQUE,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_bill_id) REFERENCES vendor_bills(id),
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id),
    CHECK (amount > 0)
);

CREATE TABLE IF NOT EXISTS bank_import_batches (
    id INTEGER PRIMARY KEY,
    bank_account_id INTEGER NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    imported_by_user_id INTEGER,
    source_filename TEXT,
    statement_start_date TEXT,
    statement_end_date TEXT,
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id),
    FOREIGN KEY (imported_by_user_id) REFERENCES users(id),
    CHECK (
        statement_start_date IS NULL
        OR statement_end_date IS NULL
        OR statement_end_date >= statement_start_date
    )
);

CREATE TABLE IF NOT EXISTS bank_transactions (
    id INTEGER PRIMARY KEY,
    bank_account_id INTEGER NOT NULL,
    import_batch_id INTEGER,
    transaction_date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    external_reference TEXT,
    matched_journal_entry_id INTEGER,
    reconciliation_status TEXT NOT NULL DEFAULT 'UNMATCHED'
        CHECK (reconciliation_status IN ('UNMATCHED', 'MATCHED', 'CLEARED')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id),
    FOREIGN KEY (import_batch_id) REFERENCES bank_import_batches(id),
    FOREIGN KEY (matched_journal_entry_id) REFERENCES journal_entries(id)
);

CREATE TABLE IF NOT EXISTS bank_reconciliations (
    id INTEGER PRIMARY KEY,
    bank_account_id INTEGER NOT NULL,
    statement_ending_date TEXT NOT NULL,
    statement_ending_balance NUMERIC NOT NULL,
    book_balance NUMERIC NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('OPEN', 'FINALIZED')),
    reconciled_by_user_id INTEGER,
    reconciled_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id),
    FOREIGN KEY (reconciled_by_user_id) REFERENCES users(id),
    UNIQUE (bank_account_id, statement_ending_date)
);

CREATE TABLE IF NOT EXISTS bank_reconciliation_lines (
    id INTEGER PRIMARY KEY,
    bank_reconciliation_id INTEGER NOT NULL,
    bank_transaction_id INTEGER NOT NULL,
    cleared_flag INTEGER NOT NULL DEFAULT 1 CHECK (cleared_flag IN (0, 1)),
    FOREIGN KEY (bank_reconciliation_id) REFERENCES bank_reconciliations(id) ON DELETE CASCADE,
    FOREIGN KEY (bank_transaction_id) REFERENCES bank_transactions(id),
    UNIQUE (bank_reconciliation_id, bank_transaction_id)
);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY,
    fiscal_year INTEGER NOT NULL,
    fund_code TEXT NOT NULL
        CHECK (fund_code IN ('OPERATING', 'RESERVE', 'SPECIAL')),
    status TEXT NOT NULL DEFAULT 'DRAFT'
        CHECK (status IN ('DRAFT', 'APPROVED', 'ARCHIVED')),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (fiscal_year, fund_code)
);

CREATE TABLE IF NOT EXISTS budget_lines (
    id INTEGER PRIMARY KEY,
    budget_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    fiscal_period INTEGER NOT NULL CHECK (fiscal_period BETWEEN 1 AND 12),
    budget_amount NUMERIC NOT NULL,
    FOREIGN KEY (budget_id) REFERENCES budgets(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    UNIQUE (budget_id, account_id, fiscal_period)
);

CREATE TABLE IF NOT EXISTS reserve_components (
    id INTEGER PRIMARY KEY,
    component_name TEXT NOT NULL,
    useful_life_years INTEGER,
    remaining_life_years INTEGER,
    current_replacement_cost NUMERIC,
    funding_method TEXT,
    notes TEXT,
    active_flag INTEGER NOT NULL DEFAULT 1 CHECK (active_flag IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reserve_transfers (
    id INTEGER PRIMARY KEY,
    transfer_date TEXT NOT NULL,
    from_account_id INTEGER NOT NULL,
    to_account_id INTEGER NOT NULL,
    amount NUMERIC NOT NULL,
    journal_entry_id INTEGER NOT NULL UNIQUE,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (from_account_id) REFERENCES accounts(id),
    FOREIGN KEY (to_account_id) REFERENCES accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id),
    CHECK (amount > 0),
    CHECK (from_account_id <> to_account_id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    file_name TEXT NOT NULL,
    mime_type TEXT,
    storage_path TEXT NOT NULL,
    uploaded_by_user_id INTEGER,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (uploaded_by_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    event_time TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    ip_address TEXT,
    user_agent TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_journal_entries_entry_date ON journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_journal_lines_account_id ON journal_entry_lines(account_id);
CREATE INDEX IF NOT EXISTS idx_journal_lines_owner_id ON journal_entry_lines(owner_id);
CREATE INDEX IF NOT EXISTS idx_journal_lines_lot_id ON journal_entry_lines(lot_id);
CREATE INDEX IF NOT EXISTS idx_assessments_owner_id ON assessments(owner_id);
CREATE INDEX IF NOT EXISTS idx_assessments_lot_id ON assessments(lot_id);
CREATE INDEX IF NOT EXISTS idx_assessments_due_date ON assessments(due_date);
CREATE INDEX IF NOT EXISTS idx_payments_owner_id ON payments(owner_id);
CREATE INDEX IF NOT EXISTS idx_vendor_bills_vendor_id ON vendor_bills(vendor_id);
CREATE INDEX IF NOT EXISTS idx_bank_transactions_bank_account_date ON bank_transactions(bank_account_id, transaction_date);
CREATE INDEX IF NOT EXISTS idx_lot_ownership_lot_id ON lot_ownership(lot_id);
CREATE INDEX IF NOT EXISTS idx_lot_ownership_owner_id ON lot_ownership(owner_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log(entity_type, entity_id);

INSERT OR IGNORE INTO roles (id, role_code, role_name) VALUES
    (1, 'ADMIN', 'Administrator'),
    (2, 'TREASURER', 'Treasurer'),
    (3, 'BOARD_MEMBER', 'Board Member'),
    (4, 'MANAGER', 'Property Manager'),
    (5, 'READ_ONLY', 'Read Only'),
    (6, 'OWNER_PORTAL', 'Owner Portal');

INSERT OR IGNORE INTO account_types (id, code, name, normal_balance, financial_statement_group) VALUES
    (1, 'ASSET', 'Asset', 'DEBIT', 'BALANCE_SHEET'),
    (2, 'LIABILITY', 'Liability', 'CREDIT', 'BALANCE_SHEET'),
    (3, 'EQUITY', 'Equity', 'CREDIT', 'BALANCE_SHEET'),
    (4, 'INCOME', 'Income', 'CREDIT', 'INCOME_STATEMENT'),
    (5, 'EXPENSE', 'Expense', 'DEBIT', 'INCOME_STATEMENT');

COMMIT;

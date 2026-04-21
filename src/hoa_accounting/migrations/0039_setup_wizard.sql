-- Setup wizard: rename default_annual_dues → default_assessment_amount,
-- add default_billing_frequency, and seed HOA starter chart of accounts.

BEGIN;

-- Rename column by adding new one and copying data (SQLite doesn't support RENAME COLUMN pre-3.25)
ALTER TABLE hoa_profile ADD COLUMN default_assessment_amount TEXT NOT NULL DEFAULT '0.00';
ALTER TABLE hoa_profile ADD COLUMN default_billing_frequency TEXT NOT NULL DEFAULT 'annual'
    CHECK(default_billing_frequency IN ('monthly','quarterly','semi-annual','annual'));

UPDATE hoa_profile SET default_assessment_amount = default_annual_dues;

-- Seed HOA starter chart of accounts (only if no accounts exist yet)
INSERT OR IGNORE INTO accounts (account_number, account_name, account_type_id, fund_code, is_bank_account, description)
SELECT account_number, account_name, account_type_id, fund_code, is_bank_account, description
FROM (
    -- Assets
    SELECT '1010' AS account_number, 'Operating Checking'       AS account_name, 1 AS account_type_id, 'OPERATING' AS fund_code, 1 AS is_bank_account, 'Primary operating bank account' AS description
    UNION ALL SELECT '1020', 'Reserve Checking',        1, 'RESERVE',   1, 'Reserve fund bank account'
    UNION ALL SELECT '1100', 'Accounts Receivable',     1, 'OPERATING', 0, 'Amounts owed by homeowners'
    -- Liabilities
    UNION ALL SELECT '2010', 'Accounts Payable',        2, 'OPERATING', 0, 'Amounts owed to vendors'
    UNION ALL SELECT '2020', 'Prepaid Dues',            2, 'OPERATING', 0, 'Assessments received in advance'
    -- Equity
    UNION ALL SELECT '3010', 'Retained Earnings',       3, 'OPERATING', 0, 'Accumulated operating surplus or deficit'
    UNION ALL SELECT '3020', 'Reserve Fund Balance',    3, 'RESERVE',   0, 'Accumulated reserve fund balance'
    -- Income
    UNION ALL SELECT '4010', 'Dues & Assessments',      4, 'OPERATING', 0, 'Regular homeowner assessments'
    UNION ALL SELECT '4020', 'Late Fees',               4, 'OPERATING', 0, 'Late payment fees charged to homeowners'
    UNION ALL SELECT '4030', 'Interest Income',         4, 'OPERATING', 0, 'Interest earned on bank accounts'
    UNION ALL SELECT '4040', 'Miscellaneous Income',    4, 'OPERATING', 0, 'Other income not categorized elsewhere'
    -- Expenses
    UNION ALL SELECT '5010', 'Landscaping',             5, 'OPERATING', 0, 'Lawn care, tree trimming, and grounds maintenance'
    UNION ALL SELECT '5020', 'Insurance',               5, 'OPERATING', 0, 'Property and liability insurance premiums'
    UNION ALL SELECT '5030', 'Utilities',               5, 'OPERATING', 0, 'Water, electric, and other utilities for common areas'
    UNION ALL SELECT '5040', 'Repairs & Maintenance',   5, 'OPERATING', 0, 'Routine repairs and upkeep of common areas'
    UNION ALL SELECT '5050', 'Management Fees',         5, 'OPERATING', 0, 'Property management company fees'
    UNION ALL SELECT '5060', 'Administrative',          5, 'OPERATING', 0, 'Office supplies, postage, and general admin costs'
    UNION ALL SELECT '5070', 'Legal & Professional',    5, 'OPERATING', 0, 'Attorney, CPA, and other professional fees'
) AS starter
WHERE (SELECT COUNT(*) FROM accounts) = 0;

COMMIT;

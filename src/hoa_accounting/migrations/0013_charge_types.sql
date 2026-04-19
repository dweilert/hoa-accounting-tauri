-- Add charge_type to assessments so dues, late fees, and legal fees are
-- tracked separately as required for state-mandated payment application order.
-- Also seeds Late Fee Income and Legal Fee Income GL accounts.
BEGIN TRANSACTION;

-- Tag all existing assessments as dues (the only type that existed before).
ALTER TABLE assessments ADD COLUMN charge_type TEXT NOT NULL DEFAULT 'DUES';

-- Late fee and legal fee income accounts.
INSERT OR IGNORE INTO accounts
    (account_number, account_name, account_type_id, fund_code, is_bank_account, is_active, description)
SELECT '4050', 'Late Fee Income', id, 'OPERATING', 0, 1,
       'Interest charged on delinquent dues and assessments'
FROM account_types WHERE code = 'INCOME';

INSERT OR IGNORE INTO accounts
    (account_number, account_name, account_type_id, fund_code, is_bank_account, is_active, description)
SELECT '4060', 'Legal Fee Income', id, 'OPERATING', 0, 1,
       'Legal costs billed as special charges to individual lot owners'
FROM account_types WHERE code = 'INCOME';

COMMIT;

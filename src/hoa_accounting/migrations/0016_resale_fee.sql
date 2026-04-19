-- Add Resale Certificate Fee Income account (4070) to support RESALE_FEE
-- charge type. The charge_type column already accepts any TEXT value;
-- no schema change is needed to the assessments table.
BEGIN TRANSACTION;

INSERT OR IGNORE INTO accounts
    (account_number, account_name, account_type_id, fund_code, is_bank_account, is_active, description)
SELECT '4070', 'Resale Certificate Fee Income', id, 'OPERATING', 0, 1,
       'Income from resale/transfer certificate fees charged at property closing'
FROM account_types WHERE code = 'INCOME';

COMMIT;

-- Reserve fund interest income account.
--
-- The initial seed (0001) shipped exactly one Interest Income account
-- tagged OPERATING. A treasurer posting interest earned on the RESERVE
-- bank against that operating-fund account trips the per-fund balance
-- invariant (PR #2) — correctly. This migration adds the missing
-- companion account so each fund has its own interest income line.
--
-- Using INSERT OR IGNORE so the migration is safe to re-run: the
-- UNIQUE constraint on account_number makes a second apply a no-op.

BEGIN TRANSACTION;

INSERT OR IGNORE INTO accounts (
    account_number, account_name, account_type_id, fund_code,
    is_bank_account, is_active, description
) VALUES (
    '4210', 'Interest Income - Reserve', 4, 'RESERVE',
    0, 1, 'Interest earned on reserve-fund bank balances'
);

COMMIT;

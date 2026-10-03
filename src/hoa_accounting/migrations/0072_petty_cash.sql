-- Migration 0072: Petty cash fund support
--
-- Adds an is_petty_cash flag to bank_accounts so any account can be
-- designated a petty cash fund, and a petty_cash_transactions table
-- to record individual expenditures.
--
-- Replenishments are recorded as account_transfers (from checking to the
-- petty cash account) so the existing Bank Transfers screen can be used.
-- Balance = opening_balance + transfers_in - transfers_out - expenditures.

BEGIN TRANSACTION;

ALTER TABLE bank_accounts ADD COLUMN is_petty_cash INTEGER NOT NULL DEFAULT 0
  CHECK(is_petty_cash IN (0, 1));

CREATE TABLE petty_cash_transactions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  bank_account_id INTEGER NOT NULL REFERENCES bank_accounts(id),
  txn_date        TEXT    NOT NULL,
  amount          NUMERIC NOT NULL CHECK(amount > 0),
  category_id     INTEGER REFERENCES categories(id),
  description     TEXT    NOT NULL,
  receipt_ref     TEXT,
  created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

COMMIT;

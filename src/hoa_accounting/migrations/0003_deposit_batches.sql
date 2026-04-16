-- Deposit batches — batched owner-payment entry.
--
-- Real HOA bookkeeping groups owner checks into deposits (typically one
-- or two trips to the bank per month). A single bank statement line for
-- e.g. $2,400 should match a single book-side debit of $2,400, not a
-- dozen separate entries. To support that we:
--
-- 1. Drop the UNIQUE(journal_entry_id) constraint on payments so
--    multiple payment rows can share one consolidated journal entry.
--    SQLite can't drop a column-level constraint in place, so we
--    rebuild the table: rename, CREATE new shape, INSERT-SELECT, drop
--    old, rename new into place.
--
-- 2. Add a deposit_batches table. Each batch carries the deposit date,
--    bank account, total amount, and a pointer to the single JE that
--    backs it. All payments belonging to the batch reference the same
--    JE AND the batch id directly.
--
-- 3. Add a nullable deposit_batch_id on payments. A payment posted
--    outside a batch (legacy single-payment form, future imports) has
--    NULL here; payments entered via the batch form point at their
--    batch.
--
-- Foreign keys are temporarily OFF around the rebuild because the
-- payments table is referenced by payment_applications — the
-- rename-copy-drop dance would otherwise trip FK validation mid-step.
-- legacy_alter_table = ON keeps SQLite from auto-rewriting other
-- tables' FK references when we RENAME (default post-3.26 behaviour
-- would point them at _payments_old_0003, orphaning them when we
-- drop that temp table). Both pragmas go back to their defaults at
-- the end of the migration.

PRAGMA legacy_alter_table = ON;
PRAGMA foreign_keys = OFF;

BEGIN TRANSACTION;

-- ── (1) Rebuild payments without UNIQUE on journal_entry_id ────────

ALTER TABLE payments RENAME TO _payments_old_0003;

CREATE TABLE payments (
    id INTEGER PRIMARY KEY,
    receipt_number TEXT NOT NULL UNIQUE,
    owner_id INTEGER NOT NULL,
    payment_date TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    payment_method TEXT NOT NULL
        CHECK (payment_method IN ('CHECK', 'ACH', 'CASH', 'CARD', 'OTHER')),
    reference_number TEXT,
    bank_account_id INTEGER NOT NULL,
    journal_entry_id INTEGER NOT NULL,
    notes TEXT,
    deposit_batch_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_id) REFERENCES owners(id),
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id),
    CHECK (amount > 0)
);

INSERT INTO payments (
    id, receipt_number, owner_id, payment_date, amount,
    payment_method, reference_number, bank_account_id,
    journal_entry_id, notes, created_at
)
SELECT
    id, receipt_number, owner_id, payment_date, amount,
    payment_method, reference_number, bank_account_id,
    journal_entry_id, notes, created_at
FROM _payments_old_0003;

DROP TABLE _payments_old_0003;

-- Recreate the index that 0001 created for owner lookups on payments.
CREATE INDEX IF NOT EXISTS idx_payments_owner_id ON payments(owner_id);

-- ── (2) deposit_batches table ──────────────────────────────────────

CREATE TABLE deposit_batches (
    id INTEGER PRIMARY KEY,
    deposit_date TEXT NOT NULL,
    bank_account_id INTEGER NOT NULL,
    journal_entry_id INTEGER NOT NULL,
    total_amount NUMERIC NOT NULL,
    notes TEXT,
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id) ON DELETE RESTRICT,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id),
    CHECK (total_amount > 0)
);

CREATE INDEX IF NOT EXISTS idx_deposit_batches_date ON deposit_batches(deposit_date);
CREATE INDEX IF NOT EXISTS idx_deposit_batches_bank ON deposit_batches(bank_account_id);
CREATE INDEX IF NOT EXISTS idx_payments_deposit_batch ON payments(deposit_batch_id);

COMMIT;

PRAGMA legacy_alter_table = OFF;
PRAGMA foreign_keys = ON;

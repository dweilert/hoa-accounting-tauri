-- Non-dues income batches.
--
-- Parallel to deposit_batches (PR #8) but for income that hits a
-- revenue account directly rather than flowing through AR. Typical
-- users: bank interest, gate remote sales, one-off fees. A batch
-- targets ONE income account (e.g. 4200 Interest Income), debits
-- cash for the total, and credits the income account once per row —
-- with per-row owner/lot attribution where applicable.

BEGIN TRANSACTION;

CREATE TABLE income_batches (
    id INTEGER PRIMARY KEY,
    posting_date TEXT NOT NULL,
    bank_account_id INTEGER NOT NULL,
    income_account_id INTEGER NOT NULL,
    income_description TEXT NOT NULL,
    total_amount NUMERIC NOT NULL,
    notes TEXT,
    journal_entry_id INTEGER NOT NULL,
    created_by_user_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id),
    FOREIGN KEY (income_account_id) REFERENCES accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id) ON DELETE RESTRICT,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id),
    CHECK (total_amount > 0)
);

CREATE INDEX IF NOT EXISTS idx_income_batches_date ON income_batches(posting_date);
CREATE INDEX IF NOT EXISTS idx_income_batches_account ON income_batches(income_account_id);

COMMIT;

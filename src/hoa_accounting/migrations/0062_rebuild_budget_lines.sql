-- Migration 0062: Rebuild budget_lines without the dead account_id column.
--
-- Migration 0061 left budget_lines.account_id (NOT NULL, FK to dropped accounts)
-- behind because dropping a UNIQUE column requires a table rebuild. The column
-- and its FK are now reachable and need to go: category_id is the source of
-- truth for budget classification.

PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS budget_lines__new;

CREATE TABLE budget_lines__new (
    id            INTEGER PRIMARY KEY,
    budget_id     INTEGER NOT NULL REFERENCES budgets(id) ON DELETE CASCADE,
    category_id   INTEGER NOT NULL REFERENCES categories(id),
    fiscal_period INTEGER NOT NULL CHECK (fiscal_period BETWEEN 1 AND 12),
    budget_amount NUMERIC NOT NULL,
    UNIQUE (budget_id, category_id, fiscal_period)
);

-- Copy any rows that already have a category_id; lines that only had the
-- legacy account_id are dropped (no live data after 0061's wipe).
INSERT INTO budget_lines__new (id, budget_id, category_id, fiscal_period, budget_amount)
SELECT id, budget_id, category_id, fiscal_period, budget_amount
FROM budget_lines
WHERE category_id IS NOT NULL;

DROP TABLE budget_lines;
ALTER TABLE budget_lines__new RENAME TO budget_lines;

PRAGMA foreign_keys = ON;

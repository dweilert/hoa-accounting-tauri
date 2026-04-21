ALTER TABLE budget_lines ADD COLUMN category_id INTEGER REFERENCES categories(id);

CREATE UNIQUE INDEX idx_budget_lines_category
ON budget_lines (budget_id, category_id, fiscal_period)
WHERE category_id IS NOT NULL;

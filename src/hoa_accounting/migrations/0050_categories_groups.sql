-- Migration 0050: Add group_name and description columns to categories.
--
-- group_name lets the HOA cluster related expense categories for reporting
-- (e.g. "Landscaping" → "General Landscaping", "Front Entrance Grounds").
-- description lets the treasurer add a plain-English note on each category.

BEGIN TRANSACTION;

ALTER TABLE categories ADD COLUMN group_name   TEXT;
ALTER TABLE categories ADD COLUMN description  TEXT;

COMMIT;

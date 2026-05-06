-- Migration 0068: Add system_required flag to categories; fix LATE_FEES → LATE_FEE.
--
-- Three category codes are looked up by name in application code and must
-- always exist:
--   DUES       — assessed homeowner dues (initializer, deposit, billing)
--   LATE_FEE   — late fee posting (late_fee_pages)
--   RESALE_FEE — resale certificate fee posting (resale_fee_pages)
--
-- The existing LATE_FEES category (code with trailing S) does not match
-- the code the late-fee feature looks for, so it is renamed here.
-- system_required = 1 prevents the category from being deleted via the UI.

BEGIN TRANSACTION;

-- 1. Add the system_required column (default 0 = not required).
ALTER TABLE categories ADD COLUMN system_required INTEGER NOT NULL DEFAULT 0
    CHECK (system_required IN (0, 1));

-- 2. Fix the code mismatch: LATE_FEES → LATE_FEE.
UPDATE categories SET code = 'LATE_FEE' WHERE code = 'LATE_FEES';

-- 3. Mark the three system-required categories.
UPDATE categories SET system_required = 1
WHERE code IN ('DUES', 'LATE_FEE', 'RESALE_FEE');

COMMIT;

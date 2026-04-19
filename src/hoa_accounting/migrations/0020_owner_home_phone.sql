-- Migration 0020: Add home_phone column to owners.
-- Existing phone column is treated as cell phone going forward.

BEGIN;
ALTER TABLE owners ADD COLUMN home_phone TEXT;
COMMIT;

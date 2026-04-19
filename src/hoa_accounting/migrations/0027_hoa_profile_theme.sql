-- Add theme preference to hoa_profile so it persists across restarts.
ALTER TABLE hoa_profile ADD COLUMN theme TEXT NOT NULL DEFAULT 'warm';

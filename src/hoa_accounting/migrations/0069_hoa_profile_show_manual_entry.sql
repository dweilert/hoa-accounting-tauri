-- Add show_manual_entry flag to hoa_profile (default 0 = hidden).
ALTER TABLE hoa_profile ADD COLUMN show_manual_entry INTEGER NOT NULL DEFAULT 0;

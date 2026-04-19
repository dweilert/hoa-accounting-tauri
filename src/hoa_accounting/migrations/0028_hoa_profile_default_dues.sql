-- Add default annual dues amount to hoa_profile for pre-filling assessment billing.
ALTER TABLE hoa_profile ADD COLUMN default_annual_dues TEXT NOT NULL DEFAULT '0.00';

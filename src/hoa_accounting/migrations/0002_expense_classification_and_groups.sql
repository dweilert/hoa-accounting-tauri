-- HOA expense classification and group_code seed.
--
-- Adds two dimensions the real-world HOA spreadsheet already uses:
--   1. accounts.group_code — the expense group each account rolls up to
--      (LANDSCAPE / SEWER / ROAD / WALL / ENTRANCE / UTILITIES /
--       INSURANCE / MISC / FIREWISE). Nullable for non-expense accounts.
--   2. journal_entry_lines.expense_classification — per-transaction tag:
--      OPERATING (routine, part of annual operating budget) or
--      IMPROVEMENT (upgrade/enhancement, not routine). Nullable on
--      non-expense lines (assets/liabilities/income/equity).
--
-- Also seeds 18 fine-grained expense accounts that replace the original
-- generic expense accounts. The old accounts are flagged inactive rather
-- than deleted so any historical journal activity remains intact.
--
-- Account-number scheme (6xxx):
--   61xx = Landscape   62xx = Sewer     63xx = Road     64xx = Wall
--   65xx = Entrance    66xx = Utilities 67xx = Insurance
--   68xx = Misc        69xx = Firewise

BEGIN TRANSACTION;

-- 1. New columns --------------------------------------------------------

ALTER TABLE accounts ADD COLUMN group_code TEXT
  CHECK (
    group_code IS NULL
    OR group_code IN (
      'LANDSCAPE', 'SEWER', 'ROAD', 'WALL', 'ENTRANCE',
      'UTILITIES', 'INSURANCE', 'MISC', 'FIREWISE'
    )
  );

ALTER TABLE journal_entry_lines ADD COLUMN expense_classification TEXT
  CHECK (
    expense_classification IS NULL
    OR expense_classification IN ('OPERATING', 'IMPROVEMENT')
  );

-- 2. Deactivate the old generic expense accounts ------------------------
-- These were seeded by the initial bootstrap for demo purposes. They
-- stay in the database to preserve any linked journal history, but are
-- hidden from pickers via is_active = 0.

UPDATE accounts SET is_active = 0
  WHERE account_number IN ('6000', '6010', '6020', '6030', '6040', '6050', '6100');

-- 3. Seed the fine-grained expense accounts ----------------------------
-- account_type_id = 5 is EXPENSE per the initial seed in 0001_initial.sql.
-- All seeded with fund_code OPERATING; Reserve-funded work is recorded
-- per-transaction via ReserveTransferService, not by duplicating accounts.

INSERT INTO accounts (
  account_number, account_name, account_type_id, fund_code,
  is_bank_account, is_active, description, group_code
) VALUES
  ('6101','Landscape - Mow & Blow',       5,'OPERATING',0,1,'Routine mowing and cleanup service',         'LANDSCAPE'),
  ('6102','Landscape - Sprinkler System', 5,'OPERATING',0,1,'Sprinkler repair and replacement',           'LANDSCAPE'),
  ('6103','Landscape - Lighting System',  5,'OPERATING',0,1,'Common-area lighting',                       'LANDSCAPE'),
  ('6104','Landscape - Mulch',            5,'OPERATING',0,1,'Mulch purchase and spread',                  'LANDSCAPE'),
  ('6105','Landscape - Tree Trimming',    5,'OPERATING',0,1,'Tree trimming and removal',                  'LANDSCAPE'),
  ('6106','Landscape - Bed Maintenance',  5,'OPERATING',0,1,'Planter bed upkeep',                         'LANDSCAPE'),
  ('6107','Landscape - Hill Maintenance', 5,'OPERATING',0,1,'Slope maintenance',                          'LANDSCAPE'),
  ('6108','Landscape - Plants',           5,'OPERATING',0,1,'Plant purchases and replacements',           'LANDSCAPE'),
  ('6109','Landscape - Other',            5,'OPERATING',0,1,'Landscape spending not covered by other lines','LANDSCAPE'),
  ('6201','Sewer',                        5,'OPERATING',0,1,'Sewer-related expenses',                     'SEWER'),
  ('6301','Road',                         5,'OPERATING',0,1,'Road-related expenses',                      'ROAD'),
  ('6401','Wall',                         5,'OPERATING',0,1,'Perimeter and retaining-wall expenses',      'WALL'),
  ('6501','Entrance - Gate',              5,'OPERATING',0,1,'Gate hardware and service',                  'ENTRANCE'),
  ('6502','Entrance - Mail Kiosk',        5,'OPERATING',0,1,'Mail kiosk upkeep',                          'ENTRANCE'),
  ('6601','Utilities',                    5,'OPERATING',0,1,'Utility bills for common areas',             'UTILITIES'),
  ('6701','Insurance',                    5,'OPERATING',0,1,'HOA liability and property insurance',       'INSURANCE'),
  ('6801','Misc',                         5,'OPERATING',0,1,'Miscellaneous expenses',                     'MISC'),
  ('6901','Firewise',                     5,'OPERATING',0,1,'Firewise community program spending',        'FIREWISE');

COMMIT;

-- Drop the redundant group prefix from expense category account names.
--
-- The seed in 0002 named the Landscape categories like 'Landscape - Mow
-- & Blow' and the Entrance categories like 'Entrance - Gate'. That was
-- belt-and-suspenders — the group is already carried on accounts.group_code
-- and surfaces as a separate column in reports. The prefix just made the
-- category column longer without adding information.
--
-- All other category names already match the user's spreadsheet exactly
-- (Sewer, Road, Wall, Utilities, Insurance, Misc, Firewise) so they're
-- left untouched.
--
-- Idempotent: if the names are already the new values (migration already
-- applied, or rows manually renamed) the UPDATE touches no rows.

BEGIN TRANSACTION;

UPDATE accounts SET account_name = 'Mow & Blow'         WHERE account_number = '6101';
UPDATE accounts SET account_name = 'Sprinkler System'   WHERE account_number = '6102';
UPDATE accounts SET account_name = 'Lighting System'    WHERE account_number = '6103';
UPDATE accounts SET account_name = 'Mulch'              WHERE account_number = '6104';
UPDATE accounts SET account_name = 'Tree Trimming'      WHERE account_number = '6105';
UPDATE accounts SET account_name = 'Bed Maintenance'    WHERE account_number = '6106';
UPDATE accounts SET account_name = 'Hill Maintenance'   WHERE account_number = '6107';
UPDATE accounts SET account_name = 'Plants'             WHERE account_number = '6108';
UPDATE accounts SET account_name = 'Other'              WHERE account_number = '6109';
UPDATE accounts SET account_name = 'Gate'               WHERE account_number = '6501';
UPDATE accounts SET account_name = 'Mail Kiosk'         WHERE account_number = '6502';

COMMIT;

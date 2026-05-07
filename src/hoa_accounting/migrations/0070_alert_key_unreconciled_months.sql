-- Migration 0070: Retire the period-close concept on the dashboard alerts.
-- Bank reconciliation is the real monthly close, so the "Unclosed accounting
-- periods" alert is reframed as "Unreconciled prior months" and its query
-- (in DashboardRepository.get_next_action_nudges) now flags completed
-- calendar months that have no FINALIZED bank reconciliation.

BEGIN TRANSACTION;

-- Rename the existing setting row in place to preserve the user's
-- enable/disable preference. If a fresh install has not yet run 0032,
-- the INSERT in 0032 will land first and this UPDATE then renames it.
UPDATE dashboard_alert_settings
   SET alert_key   = 'unreconciled_months',
       label       = 'Unreconciled prior months',
       description = 'Prior calendar months that have no finalized bank reconciliation.'
 WHERE alert_key = 'open_periods';

-- Belt-and-braces: insert the new key if neither row exists yet.
INSERT OR IGNORE INTO dashboard_alert_settings (alert_key, label, description, enabled)
VALUES (
    'unreconciled_months',
    'Unreconciled prior months',
    'Prior calendar months that have no finalized bank reconciliation.',
    1
);

COMMIT;

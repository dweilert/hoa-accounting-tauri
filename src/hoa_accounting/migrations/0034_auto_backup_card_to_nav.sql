-- Migration 0034: Move Last Auto-Backup from FINANCIAL tile to NAV quick-action card

UPDATE dashboard_cards
SET card_type   = 'NAV',
    target_url  = '/admin/database',
    description = 'View backup history and manually trigger a database backup'
WHERE id = 203;

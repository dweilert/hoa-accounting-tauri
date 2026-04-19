-- Startup backup log and new dashboard catalog cards.

CREATE TABLE IF NOT EXISTS startup_backups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    backed_up_at    TEXT NOT NULL DEFAULT (datetime('now')),
    file_path       TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_startup_backups_time
    ON startup_backups (backed_up_at DESC);

-- New system catalog cards (AR by Lot, Audit Log, Year-End Close, Last Auto-Backup).
-- INSERT OR IGNORE so re-running the migration is safe.
INSERT OR IGNORE INTO dashboard_cards
    (id, title, description, card_type, target_url, report_name, color, is_system, is_active, sort_order)
VALUES
    (200, 'AR by Lot',       'Open balances and aging by lot',              'NAV',       '/ar/lots',          NULL,              '#6d9eeb', 1, 1, 200),
    (201, 'Audit Log',       'Who changed what and when',                   'NAV',       '/admin/audit-log',  NULL,              '#b4a7d6', 1, 1, 201),
    (202, 'Year-End Close',  'Close fiscal year and post closing entries',  'NAV',       '/year-end-close',   NULL,              '#93c47d', 1, 1, 202),
    (203, 'Last Auto-Backup','Most recent scheduled startup backup',        'FINANCIAL', NULL,                'last_auto_backup','#76a5af', 1, 1, 203);

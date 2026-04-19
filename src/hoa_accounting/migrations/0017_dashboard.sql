-- Migration 0013: Dashboard card catalog and layout
--
-- dashboard_cards  : catalog of all available cards (system + user-created)
-- dashboard_layout : which cards appear on the dashboard and in what position

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS dashboard_cards (
    id          INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL,
    description TEXT,
    card_type   TEXT    NOT NULL DEFAULT 'NAV'
                CHECK (card_type IN ('NAV', 'REPORT', 'COMMENT')),
    target_url  TEXT,
    report_name TEXT,
    color       TEXT    NOT NULL DEFAULT 'green',
    is_system   INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dashboard_layout (
    id         INTEGER PRIMARY KEY,
    card_id    INTEGER NOT NULL REFERENCES dashboard_cards(id) ON DELETE CASCADE,
    position   INTEGER NOT NULL,
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (card_id),
    UNIQUE (position)
);

-- Seed default system cards
INSERT OR IGNORE INTO dashboard_cards (title, description, card_type, target_url, color, is_system, sort_order) VALUES
  ('Bill Dues',              'Post monthly dues assessments for all active lots',          'NAV', '/dues-billing',      'green',  1, 1),
  ('Bill Assessments',       'Issue special assessments to lot owners',                    'NAV', '/assessments/bill',  'green',  1, 2),
  ('Post Payments',          'Record owner payments and apply to open assessments',        'NAV', '/deposits',          'blue',   1, 3),
  ('Vendor Bills',           'Enter vendor invoices and record payments',                  'NAV', '/vendor-bills',      'orange', 1, 4),
  ('Non-Dues Income',        'Record interest, fees, and other non-dues income',           'NAV', '/income',            'teal',   1, 5),
  ('Bank Reconciliation',    'Reconcile bank statement to book balance',                   'NAV', '/reconciliations',   'purple', 1, 6),
  ('Journal Entry',          'Post a manual adjusting journal entry to the GL',            'NAV', '/journal-entries',   'slate',  1, 7),
  ('Owner Ledger PDFs',      'Generate and publish monthly owner ledger reports to S3',    'NAV', '/batch-pdf',         'red',    1, 8),
  ('Resale Certificate Fee', 'Record a resale certificate fee and payment for a lot sale', 'NAV', '/resale-fee',        'yellow', 1, 9);

-- Put all 9 system cards on the dashboard by default
INSERT OR IGNORE INTO dashboard_layout (card_id, position)
SELECT id, sort_order - 1 FROM dashboard_cards WHERE is_system = 1;

COMMIT;

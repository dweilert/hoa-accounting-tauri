-- Migration 0018: FINANCIAL card type, financial summary cards, expanded catalog

BEGIN TRANSACTION;

-- Recreate dashboard_cards with FINANCIAL added to card_type CHECK
CREATE TABLE dashboard_cards_new (
    id          INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL,
    description TEXT,
    card_type   TEXT    NOT NULL DEFAULT 'NAV'
                CHECK (card_type IN ('NAV', 'REPORT', 'COMMENT', 'FINANCIAL')),
    target_url  TEXT,
    report_name TEXT,
    color       TEXT    NOT NULL DEFAULT '#4a5462',
    is_system   INTEGER NOT NULL DEFAULT 0,
    is_active   INTEGER NOT NULL DEFAULT 1,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO dashboard_cards_new SELECT * FROM dashboard_cards;
DROP TABLE dashboard_cards;
ALTER TABLE dashboard_cards_new RENAME TO dashboard_cards;

-- ── Financial summary cards (system) ───────────────────────────────────────
INSERT OR IGNORE INTO dashboard_cards
    (id, title, description, card_type, report_name, color, is_system, sort_order)
VALUES
  (100, 'Bank Balances',
        'Current balances for all active bank accounts',
        'FINANCIAL', 'bank_tiles', '#2f6046', 1, 10),
  (101, 'Budget vs Actual',
        'Year-to-date spending vs approved budget',
        'FINANCIAL', 'budget_ytd', '#7a5312', 1, 11),
  (102, 'Last Reconciliation',
        'Most recent bank reconciliation ending balance and date',
        'FINANCIAL', 'last_recon', '#5a3a7a', 1, 12);

-- Restore layout entries for original 9 NAV cards (cascade-deleted when table was dropped above)
INSERT OR IGNORE INTO dashboard_layout (card_id, position)
SELECT id, sort_order - 1 FROM dashboard_cards
WHERE is_system = 1 AND card_type = 'NAV' AND sort_order BETWEEN 1 AND 9;

-- Put financial cards on the dashboard (positions 10-12)
INSERT OR IGNORE INTO dashboard_layout (card_id, position)
SELECT id, sort_order FROM dashboard_cards WHERE id IN (100, 101, 102);

-- ── Additional NAV cards (in catalog, not on dashboard by default) ──────────
INSERT OR IGNORE INTO dashboard_cards
    (id, title, description, card_type, target_url, color, is_system, sort_order)
VALUES
  (103, 'Reserve Transfers',
        'Record transfers between operating and reserve accounts',
        'NAV', '/reserve-transfers', '#0f7173', 1, 13),
  (104, 'Opening Balances',
        'Set starting balances for lots and bank accounts',
        'NAV', '/opening-balances', '#4a5462', 1, 14),
  (105, 'GL Import',
        'Import general ledger transactions from a CSV file',
        'NAV', '/gl-import', '#9a3060', 1, 15),
  (106, 'Lot Management',
        'View and manage lots, owners, and contact information',
        'NAV', '/lots', '#1f4d7a', 1, 16),
  (107, 'Vendor Management',
        'Add and manage vendors used for HOA expenses',
        'NAV', '/vendors', '#c26000', 1, 17),
  (108, 'Charge Types',
        'Configure dues and assessment charge type codes',
        'NAV', '/charge-types', '#4a5462', 1, 18);

-- ── Report cards (in catalog, not on dashboard by default) ─────────────────
INSERT OR IGNORE INTO dashboard_cards
    (id, title, description, card_type, report_name, color, is_system, sort_order)
VALUES
  (110, 'Owner Ledger Report',
        'Per-owner statement of charges and payments',
        'REPORT', 'owner-ledger', '#1f4d7a', 1, 20),
  (111, 'Balance Sheet',
        'Assets, liabilities, and equity at a point in time',
        'REPORT', 'balance-sheet', '#2f6046', 1, 21),
  (112, 'Income Statement',
        'Revenue and expenses for the fiscal year',
        'REPORT', 'income-statement', '#c26000', 1, 22),
  (113, 'Trial Balance',
        'Debit and credit totals for all GL accounts',
        'REPORT', 'trial-balance', '#4a5462', 1, 23),
  (114, 'AR Aging',
        'Outstanding lot balances by age bucket',
        'REPORT', 'ar-aging', '#9a3a38', 1, 24),
  (115, 'Budget vs Actual Report',
        'Detailed budget line comparison to actual expenses',
        'REPORT', 'expenses-vs-budget', '#7a5312', 1, 25),
  (116, 'Vendor Payment History',
        'Payments made to vendors over a date range',
        'REPORT', 'vendor-expenses', '#0f7173', 1, 26);

COMMIT;

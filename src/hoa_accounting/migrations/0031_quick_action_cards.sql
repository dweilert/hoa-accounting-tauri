-- Migration 0031: Quick Action dashboard cards + default layout snapshot table

BEGIN TRANSACTION;

-- ── Quick Action NAV cards ──────────────────────────────────────────────────
-- These deep-link to Record an Adjustment (/journal-entries/new?scenario=<id>)
INSERT OR IGNORE INTO dashboard_cards
    (id, title, description, card_type, target_url, color, is_system, is_active, sort_order)
VALUES
  (300, 'Record Bank Interest',
        'Record monthly interest earned on a bank account',
        'NAV', '/journal-entries/new?scenario=bank_interest', '#2f6046', 1, 1, 300),
  (301, 'Record a Bank Fee',
        'Record a bank service charge or fee',
        'NAV', '/journal-entries/new?scenario=bank_fee', '#9a3a38', 1, 1, 301),
  (302, 'Transfer Between Accounts',
        'Move money between HOA bank accounts',
        'NAV', '/journal-entries/new?scenario=bank_transfer', '#0f7173', 1, 1, 302),
  (303, 'Waive a Late Fee',
        'Remove a previously charged late fee for a homeowner',
        'NAV', '/journal-entries/new?scenario=waive_late_fee', '#7a5312', 1, 1, 303),
  (304, 'NSF / Bounced Check',
        'Reverse a payment that was returned by the bank',
        'NAV', '/journal-entries/new?scenario=nsf_check', '#9a3060', 1, 1, 304),
  (305, 'Refund a Homeowner',
        'Record a refund issued to a homeowner',
        'NAV', '/journal-entries/new?scenario=vendor_refund', '#1f4d7a', 1, 1, 305);

-- ── SECTION divider cards ───────────────────────────────────────────────────
INSERT OR IGNORE INTO dashboard_cards
    (id, title, description, card_type, color, is_system, is_active, sort_order)
VALUES
  (310, 'Monthly Tasks',    'Section divider — monthly recurring actions', 'SECTION', '#4a5462', 1, 1, 310),
  (311, 'When Needed',      'Section divider — on-demand actions',         'SECTION', '#4a5462', 1, 1, 311),
  (312, 'Reports',          'Section divider — reporting and exports',     'SECTION', '#4a5462', 1, 1, 312),
  (313, 'Financial Summary','Section divider — financial overview tiles',  'SECTION', '#4a5462', 1, 1, 313);

-- ── Default layout snapshot table ──────────────────────────────────────────
-- Stores the canonical default order so "Reset to Default" can restore it.
CREATE TABLE IF NOT EXISTS dashboard_default_layout (
    position  INTEGER PRIMARY KEY,
    card_id   INTEGER NOT NULL REFERENCES dashboard_cards(id)
);

INSERT OR IGNORE INTO dashboard_default_layout (position, card_id) VALUES
  -- Financial Summary section
  (0,  313),  -- Financial Summary (section header)
  (1,  100),  -- Bank Balances
  (2,  101),  -- Budget vs Actual
  (3,  102),  -- Last Reconciliation
  -- Monthly Tasks section
  (4,  310),  -- Monthly Tasks (section header)
  (5,  300),  -- Record Bank Interest
  (6,  301),  -- Record a Bank Fee
  (7,  302),  -- Transfer Between Accounts
  (8,    1),  -- Bill Dues
  (9,    2),  -- Bill Assessments
  (10,   3),  -- Post Payments
  (11,   4),  -- Vendor Bills
  (12,   5),  -- Non-Dues Income
  (13,   6),  -- Bank Reconciliation
  -- When Needed section
  (14, 311),  -- When Needed (section header)
  (15, 303),  -- Waive a Late Fee
  (16, 304),  -- NSF / Bounced Check
  (17, 305),  -- Refund a Homeowner
  (18,   7),  -- Journal Entry
  (19,   8),  -- Owner Ledger PDFs
  (20,   9),  -- Resale Certificate Fee
  -- Reports section
  (21, 312),  -- Reports (section header)
  (22, 110),  -- Owner Ledger Report
  (23, 111),  -- Balance Sheet
  (24, 112),  -- Income Statement
  (25, 114),  -- AR Aging
  (26, 115);  -- Budget vs Actual Report

COMMIT;

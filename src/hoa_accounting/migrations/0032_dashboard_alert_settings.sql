-- Migration 0032: Dashboard alert banner settings and per-session dismissals

BEGIN TRANSACTION;

-- ── Alert settings: one row per alert type, user can enable/disable ─────────
CREATE TABLE IF NOT EXISTS dashboard_alert_settings (
    alert_key   TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    description TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1
);

INSERT OR IGNORE INTO dashboard_alert_settings (alert_key, label, description, enabled) VALUES
  ('open_periods',
   'Unclosed accounting periods',
   'Warn when prior-month accounting periods have not been locked.',
   1),
  ('open_reconciliation',
   'Bank reconciliation in progress',
   'Warn when a bank reconciliation was started but not finished.',
   1),
  ('overdue_60_days',
   'Assessments 60+ days overdue',
   'Alert when homeowner balances are more than 60 days past due.',
   1),
  ('overdue_90_days',
   'Assessments 90+ days overdue',
   'Urgent alert when homeowner balances are more than 90 days past due.',
   1),
  ('unpaid_vendor_bills',
   'Vendor bills past due',
   'Alert when approved vendor bills have not been paid by their due date.',
   1),
  ('no_recon_this_month',
   'No reconciliation completed this month',
   'Remind when no bank account has been reconciled in the current calendar month.',
   1),
  ('fiscal_year_not_closed',
   'Prior fiscal year not closed',
   'Alert after January 1st if the previous fiscal year has not been closed.',
   1),
  ('reserve_study_old',
   'Reserve study may be outdated',
   'Remind when no reserve study has been recorded in the past 3 years.',
   1);

-- ── Per-session dismissals: cleared at each server startup ──────────────────
CREATE TABLE IF NOT EXISTS dashboard_alert_dismissals (
    alert_key    TEXT PRIMARY KEY,
    dismissed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

COMMIT;

-- ── Expense vs Budget summary financial card ────────────────────────────────
INSERT OR IGNORE INTO dashboard_cards
    (id, title, description, card_type, report_name, color, is_system, is_active, sort_order)
VALUES
  (400, 'Expense vs Budget',
        'Percent of annual budget spent, categories over and under budget',
        'FINANCIAL', 'budget_categories', '#7a5312', 1, 1, 13);

-- Performance indexes on frequently-filtered date columns.
CREATE INDEX IF NOT EXISTS idx_assessments_assessment_date
    ON assessments (assessment_date);

CREATE INDEX IF NOT EXISTS idx_journal_entries_posted_at
    ON journal_entries (posted_at);

CREATE INDEX IF NOT EXISTS idx_vendor_bills_due_date
    ON vendor_bills (due_date);

-- Workflow Guide card in the dashboard catalog.
INSERT OR IGNORE INTO dashboard_cards
    (id, title, description, card_type, target_url, report_name, color, is_system, is_active, sort_order)
VALUES
    (204, 'Workflow Guide',
     'Step-by-step playbooks for monthly close, quarter end, year end, and common adjustments',
     'NAV', '/workflow-guide', NULL, '#0f7173', 1, 1, 204);

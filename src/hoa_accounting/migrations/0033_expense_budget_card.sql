-- Migration 0033: Expense vs Budget financial summary card

INSERT OR IGNORE INTO dashboard_cards
    (id, title, description, card_type, report_name, color, is_system, is_active, sort_order)
VALUES
  (400, 'Expense vs Budget',
        'Percent of annual budget spent, and count of expense categories over and under budget',
        'FINANCIAL', 'budget_categories', '#7a5312', 1, 1, 400);

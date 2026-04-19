-- Migration 0035: Retire the Budget vs Actual financial tile (superseded by Expense vs Budget)

UPDATE dashboard_cards SET is_active = 0 WHERE id = 101;
DELETE FROM dashboard_layout WHERE card_id = 101;
DELETE FROM dashboard_default_layout WHERE card_id = 101;

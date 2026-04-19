-- Migration 0019: Add SECTION card type for dashboard section dividers

BEGIN TRANSACTION;

-- Recreate dashboard_cards with SECTION added to card_type CHECK
CREATE TABLE dashboard_cards_new (
    id          INTEGER PRIMARY KEY,
    title       TEXT    NOT NULL,
    description TEXT,
    card_type   TEXT    NOT NULL DEFAULT 'NAV'
                CHECK (card_type IN ('NAV', 'REPORT', 'COMMENT', 'FINANCIAL', 'SECTION')),
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

-- Restore layout entries dropped by cascade above
INSERT OR IGNORE INTO dashboard_layout (card_id, position)
SELECT id, sort_order - 1 FROM dashboard_cards
WHERE is_system = 1 AND card_type = 'NAV' AND sort_order BETWEEN 1 AND 9;

INSERT OR IGNORE INTO dashboard_layout (card_id, position)
SELECT id, sort_order FROM dashboard_cards WHERE id IN (100, 101, 102);

COMMIT;

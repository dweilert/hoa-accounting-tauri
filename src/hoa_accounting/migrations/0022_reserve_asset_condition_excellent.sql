BEGIN;

-- SQLite does not support ALTER TABLE to change a CHECK constraint.
-- Rebuild reserve_assets with the updated condition check that includes 'Excellent'.

CREATE TABLE reserve_assets_new (
    id              INTEGER PRIMARY KEY,
    asset_group     TEXT NOT NULL,
    component       TEXT NOT NULL,
    install_year    INTEGER NOT NULL,
    useful_life_years INTEGER NOT NULL,
    condition       TEXT NOT NULL DEFAULT 'Good'
                        CHECK (condition IN ('Excellent','Good','Moderate','Poor','Critical')),
    replacement_cost NUMERIC NOT NULL DEFAULT 0,
    annual_inflation NUMERIC NOT NULL DEFAULT 0.04,
    notes           TEXT,
    active_flag     INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO reserve_assets_new SELECT * FROM reserve_assets;

DROP TABLE reserve_assets;
ALTER TABLE reserve_assets_new RENAME TO reserve_assets;

COMMIT;

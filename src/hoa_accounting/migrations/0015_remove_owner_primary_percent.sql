-- Migration 0015: Remove primary-contact flag and ownership percent
--
-- The "Owner 1 / Owner 2" distinction is replaced with a flat list of owners
-- per lot (unlimited count, no primary designation).  The ownership_percent
-- column was never surfaced in the UI and is being dropped to keep the schema
-- clean.  The same primary-contact concept is removed from lot_renters.
--
-- Both columns are referenced in CHECK constraints, so we must recreate the
-- tables (SQLite does not support DROP COLUMN on constrained columns).

PRAGMA foreign_keys = OFF;

-- ── lot_ownership ──────────────────────────────────────────────────────────

CREATE TABLE lot_ownership_new (
    id         INTEGER PRIMARY KEY,
    lot_id     INTEGER NOT NULL,
    owner_id   INTEGER NOT NULL,
    start_date TEXT    NOT NULL,
    end_date   TEXT,
    FOREIGN KEY (lot_id)   REFERENCES lots(id),
    FOREIGN KEY (owner_id) REFERENCES owners(id)
);

INSERT INTO lot_ownership_new (id, lot_id, owner_id, start_date, end_date)
SELECT id, lot_id, owner_id, start_date, end_date
FROM lot_ownership;

DROP TABLE lot_ownership;

ALTER TABLE lot_ownership_new RENAME TO lot_ownership;

CREATE INDEX idx_lot_ownership_lot_id   ON lot_ownership(lot_id);
CREATE INDEX idx_lot_ownership_owner_id ON lot_ownership(owner_id);

-- ── lot_renters ────────────────────────────────────────────────────────────

CREATE TABLE lot_renters_new (
    id           INTEGER PRIMARY KEY,
    lot_id       INTEGER NOT NULL,
    display_name TEXT    NOT NULL,
    first_name   TEXT,
    last_name    TEXT,
    email        TEXT,
    phone        TEXT,
    start_date   TEXT    NOT NULL,
    end_date     TEXT,
    notes        TEXT,
    created_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lot_id) REFERENCES lots(id),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

INSERT INTO lot_renters_new (
    id, lot_id, display_name, first_name, last_name,
    email, phone, start_date, end_date, notes, created_at, updated_at
)
SELECT
    id, lot_id, display_name, first_name, last_name,
    email, phone, start_date, end_date, notes, created_at, updated_at
FROM lot_renters;

DROP TABLE lot_renters;

ALTER TABLE lot_renters_new RENAME TO lot_renters;

CREATE INDEX idx_lot_renters_lot_id ON lot_renters(lot_id);
CREATE INDEX idx_lot_renters_active ON lot_renters(lot_id, end_date);

PRAGMA foreign_keys = ON;

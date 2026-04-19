-- Migration 0012: Split lot opening balances into dues and assessment subtypes
--
-- Extends opening_balances to support LOT_DUES and LOT_ASSESSMENT entity types.
-- Existing LOT records are migrated to LOT_DUES.

BEGIN TRANSACTION;

CREATE TABLE opening_balances_new (
    id               INTEGER PRIMARY KEY,
    entity_type      TEXT    NOT NULL CHECK (entity_type IN ('BANK_ACCOUNT', 'LOT_DUES', 'LOT_ASSESSMENT')),
    entity_id        INTEGER NOT NULL,
    as_of_date       TEXT    NOT NULL,
    amount           NUMERIC NOT NULL DEFAULT 0,
    journal_entry_id INTEGER REFERENCES journal_entries(id),
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (entity_type, entity_id)
);

INSERT INTO opening_balances_new
    (id, entity_type, entity_id, as_of_date, amount, journal_entry_id, created_at, updated_at)
SELECT
    id,
    CASE entity_type WHEN 'LOT' THEN 'LOT_DUES' ELSE entity_type END,
    entity_id, as_of_date, amount, journal_entry_id, created_at, updated_at
FROM opening_balances;

DROP TABLE opening_balances;
ALTER TABLE opening_balances_new RENAME TO opening_balances;

COMMIT;

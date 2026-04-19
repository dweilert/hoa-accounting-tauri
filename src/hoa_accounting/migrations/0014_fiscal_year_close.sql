-- Migration 0014: Fiscal year close tracking
--
-- Records which fiscal years have been formally closed with closing journal
-- entries.  A row here means the year is closed; absence means it is open.
-- The reopened_at column is set when a year is re-opened for corrections;
-- deleting the row and reversing the JEs is handled by the service layer.

CREATE TABLE IF NOT EXISTS fiscal_year_closes (
    id                       INTEGER PRIMARY KEY,
    fiscal_year              INTEGER NOT NULL UNIQUE,
    closed_at                TEXT    NOT NULL,
    -- One closing JE per fund; NULL when that fund had no income/expense activity.
    closing_je_operating_id  INTEGER UNIQUE
                             REFERENCES journal_entries(id),
    closing_je_reserve_id    INTEGER UNIQUE
                             REFERENCES journal_entries(id),
    reopened_at              TEXT    -- NULL = still closed
);

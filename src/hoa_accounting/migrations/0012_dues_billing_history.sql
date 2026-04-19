-- Track each dues billing run so the UI can show the last billed cycle
-- and default to the next logical period.
BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS dues_billing_history (
    id              INTEGER PRIMARY KEY,
    cycle_type      TEXT    NOT NULL
                            CHECK (cycle_type IN ('MONTHLY','QUARTERLY','SEMIANNUAL','ANNUAL')),
    period_label    TEXT    NOT NULL,   -- human label, e.g. "January 2026"
    period_year     INTEGER NOT NULL,
    period_sequence INTEGER NOT NULL,  -- 1-12 monthly, 1-4 quarterly, 1-2 semiannual, 1 annual
    amount          NUMERIC NOT NULL,
    owner_count     INTEGER NOT NULL DEFAULT 0,
    billed_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMIT;

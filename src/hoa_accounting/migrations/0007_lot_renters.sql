-- Renter tracking.
--
-- HOA lots can be owner-occupied or rented out. Renters are NOT
-- owners — they don't get billed assessments, they don't carry AR —
-- but they're contacts for the property (package delivery, HOA
-- notices other than financial, emergency contact). Tracked in their
-- own table rather than piggy-backing on owners so the distinction
-- stays clean and AR queries can't accidentally pick them up.
--
-- Shape mirrors lot_ownership so the life-cycle semantics are
-- familiar: start_date, optional end_date, is_primary_contact to
-- flag the lead renter when multiple names live at one lot. 'Owner
-- Occupied' is a derived state — a lot is owner-occupied when it
-- has no current (end_date IS NULL) renter row.

BEGIN TRANSACTION;

CREATE TABLE lot_renters (
    id INTEGER PRIMARY KEY,
    lot_id INTEGER NOT NULL,
    display_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    phone TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT,
    is_primary_contact INTEGER NOT NULL DEFAULT 1
        CHECK (is_primary_contact IN (0, 1)),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (lot_id) REFERENCES lots(id),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_lot_renters_lot_id ON lot_renters(lot_id);
CREATE INDEX IF NOT EXISTS idx_lot_renters_active ON lot_renters(lot_id, end_date);

COMMIT;

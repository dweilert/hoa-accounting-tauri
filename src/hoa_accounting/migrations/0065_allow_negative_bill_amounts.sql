-- Migration 0065: Allow negative amounts on vendor_bills and bill_payments
--
-- Removes the CHECK (amount >= 0) constraint from vendor_bills and the
-- CHECK (amount > 0) constraint from bill_payments so that vendor credit
-- memos (refunds) can be recorded with a negative amount.
--
-- SQLite does not support ALTER TABLE DROP CONSTRAINT, so we rebuild both
-- tables using the standard rename-create-copy-drop pattern inside a
-- single transaction.

PRAGMA foreign_keys = OFF;

BEGIN;

-- ── vendor_bills ────────────────────────────────────────────────────────

ALTER TABLE vendor_bills RENAME TO _vendor_bills_old;

CREATE TABLE vendor_bills (
    id                  INTEGER PRIMARY KEY,
    vendor_id           INTEGER NOT NULL,
    invoice_number      TEXT    NOT NULL,
    invoice_date        TEXT    NOT NULL,
    due_date            TEXT,
    amount              NUMERIC NOT NULL CHECK (amount != 0),
    payable_account_id  INTEGER,
    fund_code           TEXT    NOT NULL DEFAULT 'OPERATING'
                            CHECK (fund_code IN ('OPERATING','RESERVE','SPECIAL')),
    status              TEXT    NOT NULL DEFAULT 'OPEN'
                            CHECK (status IN ('OPEN','PARTIAL','PAID','VOID')),
    description         TEXT,
    category_id         INTEGER REFERENCES categories(id),
    created_at          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_id) REFERENCES vendors(id),
    UNIQUE (vendor_id, invoice_number)
);

INSERT INTO vendor_bills SELECT * FROM _vendor_bills_old;
DROP TABLE _vendor_bills_old;

-- ── bill_payments ────────────────────────────────────────────────────────

ALTER TABLE bill_payments RENAME TO _bill_payments_old;

CREATE TABLE bill_payments (
    id               INTEGER PRIMARY KEY,
    vendor_bill_id   INTEGER NOT NULL,
    payment_date     TEXT    NOT NULL,
    amount           NUMERIC NOT NULL CHECK (amount != 0),
    bank_account_id  INTEGER NOT NULL,
    check_number     TEXT,
    notes            TEXT,
    created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (vendor_bill_id)  REFERENCES vendor_bills(id),
    FOREIGN KEY (bank_account_id) REFERENCES bank_accounts(id)
);

INSERT INTO bill_payments SELECT * FROM _bill_payments_old;
DROP TABLE _bill_payments_old;

COMMIT;

PRAGMA foreign_keys = ON;

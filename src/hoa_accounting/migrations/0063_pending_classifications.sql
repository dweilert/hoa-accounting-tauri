-- Migration 0063: Pending classifications.
--
-- A pending classification is the treasurer's pre-bank record of money
-- they expect to deposit. It captures the human knowledge that the
-- anonymous bank file (OFX) doesn't have:
--
--     "I received $155 from Bob Smith for Lot 42 dues on Jan 5,
--      check #4789, going into the Operating account."
--
-- Critically, this row does NOT post anywhere. No payments row, no
-- payment_applications, no balance change. It is purely intent.
--
-- The lifecycle:
--   PENDING   — entered by treasurer, not yet seen on the bank
--   MATCHED   — auto- or manually linked to a bank_transactions row
--               (set when OFX import finds a corresponding deposit)
--   POSTED    — Post step has created the actual payments row;
--               posted_payment_id points at it
--   CANCELLED — treasurer voided the record (e.g. check bounced and
--               no deposit will materialize)
--
-- Lot/owner are nullable so non-owner deposits (interest, refunds,
-- one-off income) can also be pre-classified.

BEGIN TRANSACTION;

CREATE TABLE pending_classifications (
    id                          INTEGER PRIMARY KEY,
    classification_date         TEXT    NOT NULL,
    expected_deposit_date       TEXT,
    bank_account_id             INTEGER NOT NULL,
    lot_id                      INTEGER,
    owner_id                    INTEGER,
    amount                      NUMERIC NOT NULL,
    payment_method              TEXT    NOT NULL DEFAULT 'CHECK'
                                    CHECK (payment_method IN
                                        ('CHECK','ACH','CASH','CARD','OTHER')),
    reference_number            TEXT,
    category_id                 INTEGER,
    charge_type                 TEXT,
    memo                        TEXT,
    status                      TEXT    NOT NULL DEFAULT 'PENDING'
                                    CHECK (status IN
                                        ('PENDING','MATCHED','POSTED','CANCELLED')),
    matched_bank_transaction_id INTEGER,
    posted_payment_id           INTEGER,
    created_by_user_id          INTEGER,
    created_at                  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bank_account_id)             REFERENCES bank_accounts(id),
    FOREIGN KEY (lot_id)                      REFERENCES lots(id),
    FOREIGN KEY (owner_id)                    REFERENCES owners(id),
    FOREIGN KEY (category_id)                 REFERENCES categories(id),
    FOREIGN KEY (matched_bank_transaction_id) REFERENCES bank_transactions(id),
    FOREIGN KEY (posted_payment_id)           REFERENCES payments(id),
    FOREIGN KEY (created_by_user_id)          REFERENCES users(id),
    CHECK (amount > 0)
);

CREATE INDEX idx_pending_classifications_status
    ON pending_classifications(status);
CREATE INDEX idx_pending_classifications_bank
    ON pending_classifications(bank_account_id);
CREATE INDEX idx_pending_classifications_lot
    ON pending_classifications(lot_id);
CREATE INDEX idx_pending_classifications_classification_date
    ON pending_classifications(classification_date);
CREATE INDEX idx_pending_classifications_matched_bt
    ON pending_classifications(matched_bank_transaction_id);

COMMIT;

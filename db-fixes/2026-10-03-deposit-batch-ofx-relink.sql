-- ============================================================
-- 2026-10-03  Deposit batch OFX re-link + data cleanup
-- ============================================================
-- Root cause: person-specific CATEGORIZE rules (Chris, Dale, Gene,
-- Caitlin) fired before deposit batch matching, creating duplicate
-- income_batches for teller deposits already recorded as check
-- payments inside deposit_batches.  Also: several Flask-migrated
-- batches incorrectly combined checks the bank processed separately.
--
-- Code fix: applyRulesToPending now checks for a deposit batch match
-- FIRST (for positive amounts) before running any rules.
-- ============================================================

-- ── 1. Create account_transfers table (new feature) ───────────────
CREATE TABLE IF NOT EXISTS account_transfers (
  id                   INTEGER PRIMARY KEY AUTOINCREMENT,
  transfer_date        TEXT    NOT NULL,
  from_account_id      INTEGER NOT NULL REFERENCES bank_accounts(id),
  to_account_id        INTEGER NOT NULL REFERENCES bank_accounts(id),
  amount               NUMERIC NOT NULL CHECK(amount > 0),
  description          TEXT,
  notes                TEXT,
  from_txn_id          INTEGER REFERENCES bank_transactions(id),
  to_txn_id            INTEGER REFERENCES bank_transactions(id),
  created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── 2. Remove duplicate income_batches created by rule mis-fires ───
-- Income batch IDs that were wrongly created (teller deposits
-- classified as HOA Dues instead of being linked to deposit batches)
DELETE FROM bank_transaction_links
WHERE bank_transaction_id IN (141,143,144,145,136,134,133,130,126,125,121,112,108,107,104,119,120)
  AND source_type = 'INCOME_BATCH';

DELETE FROM income_batches WHERE id IN (37,38,39,40,34,32,31,29,26,25,22,15,12,11,8,20,21);

-- ── 3. Link deposit batches to correct OFX transactions ───────────
UPDATE deposit_batches SET bank_transaction_id = 144 WHERE id = 29;  -- $155.06 Feb 2
UPDATE deposit_batches SET bank_transaction_id = 141 WHERE id = 31;  -- $155   Feb 5
UPDATE deposit_batches SET bank_transaction_id = 145 WHERE id = 28;  -- $150.13 Jan 30
UPDATE deposit_batches SET bank_transaction_id = 136 WHERE id = 35;  -- $150.13 Mar 2
UPDATE deposit_batches SET bank_transaction_id = 134 WHERE id = 36;  -- $155.02 Mar 5
UPDATE deposit_batches SET bank_transaction_id = 133 WHERE id = 37;  -- $155   Mar 6
UPDATE deposit_batches SET bank_transaction_id = 130 WHERE id = 72;  -- $150.13 Mar 30
UPDATE deposit_batches SET bank_transaction_id = 126 WHERE id = 41;  -- $155   Apr 3
UPDATE deposit_batches SET bank_transaction_id = 125 WHERE id = 42;  -- $155.02 Apr 6
UPDATE deposit_batches SET bank_transaction_id = 121 WHERE id = 45;  -- $150.13 Apr 30
UPDATE deposit_batches SET bank_transaction_id = 112 WHERE id = 73;  -- $150.13 Jun 1
UPDATE deposit_batches SET bank_transaction_id = 108 WHERE id = 50;  -- $155   Jun 5
UPDATE deposit_batches SET bank_transaction_id = 107 WHERE id = 51;  -- $155.02 Jun 8
UPDATE deposit_batches SET bank_transaction_id = 104 WHERE id = 53;  -- $150.13 Jun 30
UPDATE deposit_batches SET bank_transaction_id = 96  WHERE id = 54;  -- $1,085 Jul 6 (OFX Jul 10)
UPDATE deposit_batches SET bank_transaction_id = 90  WHERE id = 60;  -- $775   Aug 6 (OFX Aug 10)

-- Mark reclaimed OFX txns VALIDATED
UPDATE bank_transactions SET validation_status = 'VALIDATED'
WHERE id IN (141,144,142);

-- ── 4. Split batch 30 (incorrectly combined Feb 4 deposit) ────────
-- Dale's $155.02 was a separate teller deposit from Judy/Alica/Vicki $775
UPDATE deposit_batches
SET total_amount = 775, check_count = 3, bank_transaction_id = 142
WHERE id = 30;

INSERT INTO deposit_batches (deposit_date, bank_account_id, total_amount, check_count, status, bank_transaction_id, notes, updated_at)
VALUES ('2026-02-04', 1, 155.02, 1, 'POSTED', 143, 'Dale — split from batch 30', datetime('now'));
-- Move Dale payment (lot 4202) to new batch — payment id 172
UPDATE payments SET deposit_batch_id = (SELECT id FROM deposit_batches WHERE notes = 'Dale — split from batch 30') WHERE id = 172;
UPDATE bank_transactions SET validation_status = 'VALIDATED' WHERE id = 142;

-- ── 5. Split batch 46 (incorrectly combined May 4 deposit) ────────
UPDATE deposit_batches
SET total_amount = 155.02, check_count = 1, bank_transaction_id = 119
WHERE id = 46;

INSERT INTO deposit_batches (deposit_date, bank_account_id, total_amount, check_count, status, bank_transaction_id, notes, updated_at)
VALUES ('2026-05-04', 1, 155, 1, 'POSTED', 120, NULL, datetime('now'));
UPDATE payments SET deposit_batch_id = (SELECT MAX(id) FROM deposit_batches WHERE deposit_date='2026-05-04' AND total_amount=155) WHERE id = 210;

-- ── 6. Record Apr 2 lawn care reimbursement ($1,285) ─────────────
-- OFX 127 ($1,595) = $310 dues checks (batch 40) + $1,285 reimbursement
-- $1,285 offsets Mow & Blow expense (category 18)
INSERT INTO income_batches (income_date, bank_account_id, category_id, amount, description)
VALUES ('2026-04-02', 1, 18, 1285, 'Lawn care overpayment reimbursement');

INSERT OR IGNORE INTO bank_transaction_links (bank_transaction_id, source_type, source_id)
VALUES (127, 'INCOME_BATCH', last_insert_rowid());

UPDATE bank_transactions SET validation_status = 'VALIDATED' WHERE id = 127;

UPDATE deposit_batches
SET notes = 'Co-deposited with $1,285 lawn care reimbursement check (OFX txn 127, $1,595 total)'
WHERE id = 40;

-- ── 7. Remaining unmatched (no OFX data available) ───────────────
-- Batch 40 (Apr 1, $310): OFX missing — co-deposited with reimbursement, noted above
-- Batch 58 (Aug 1, $930): OFX missing — check physical bank statement for Aug 1

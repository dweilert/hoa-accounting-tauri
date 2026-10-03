#!/usr/bin/env bash
# Inject additional test-specific data into hoa-test.db.
# Run AFTER reset-test-db.sh if you want edge-case records for manual testing.
# Safe: never touches the live DB.

set -euo pipefail

TEST_DB="$HOME/hoa-system/tauri/hoa-test.db"

if [[ ! -f "$TEST_DB" ]]; then
  echo "ERROR: $TEST_DB not found. Run reset-test-db.sh first." >&2
  exit 1
fi

echo "Seeding test data into $TEST_DB..."

sqlite3 "$TEST_DB" <<'SQL'

-- ── NSF payment (for testing NSF reversal UI) ────────────────────────────────
-- Grab first lot and bank account for seed anchors
INSERT OR IGNORE INTO payments (
  lot_id, deposit_batch_id, payment_date, amount, payment_method, payment_type, memo
)
SELECT
  (SELECT id FROM lots ORDER BY lot_number LIMIT 1),
  NULL,
  date('now', '-10 days'),
  250.00,
  'CHECK',
  'DUES',
  'TEST: unassigned payment for NSF testing'
WHERE NOT EXISTS (
  SELECT 1 FROM payments WHERE memo = 'TEST: unassigned payment for NSF testing'
);

-- ── Open deposit batch with the above payment unassigned ─────────────────────
-- (no INSERT — just leave the payment unassigned so the Deposits screen
--  shows it in the "available payments" picker)

-- ── Other income adjustment (negative — fee/charge) ─────────────────────────
INSERT OR IGNORE INTO income_batches (
  income_date, bank_account_id, category_id, amount, description, lot_id
)
SELECT
  date('now', '-5 days'),
  (SELECT id FROM bank_accounts ORDER BY id LIMIT 1),
  (SELECT id FROM categories WHERE code = 'BANK_FEE'),
  -15.00,
  'TEST: bank service charge for Other Income testing',
  NULL
WHERE NOT EXISTS (
  SELECT 1 FROM income_batches WHERE description = 'TEST: bank service charge for Other Income testing'
);

-- ── Overdue assessment (status OPEN, date in past) ───────────────────────────
INSERT OR IGNORE INTO assessments (
  lot_id, charge_type, amount, assessment_date, due_date, status, description
)
SELECT
  (SELECT id FROM lots ORDER BY lot_number DESC LIMIT 1),
  'DUES',
  300.00,
  date('now', '-60 days'),
  date('now', '-45 days'),
  'OPEN',
  'TEST: overdue assessment for testing'
WHERE NOT EXISTS (
  SELECT 1 FROM assessments WHERE description = 'TEST: overdue assessment for testing'
);

SELECT 'Seed complete.';
SELECT 'unassigned test payments: ' || COUNT(*) FROM payments WHERE deposit_batch_id IS NULL AND memo LIKE 'TEST:%';
SELECT 'test income entries: ' || COUNT(*) FROM income_batches WHERE description LIKE 'TEST:%';
SELECT 'test assessments: ' || COUNT(*) FROM assessments WHERE description LIKE 'TEST:%';
SQL

echo "Done."

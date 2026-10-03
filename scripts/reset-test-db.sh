#!/usr/bin/env bash
# Refresh hoa-test.db from the live hoa.db.
# Run this whenever you want a clean copy of production data in the test DB.
# Safe: never touches the live DB.

set -euo pipefail

TAURI_DIR="$HOME/hoa-system/tauri"
LIVE_DB="$TAURI_DIR/hoa.db"
TEST_DB="$TAURI_DIR/hoa-test.db"

echo "Refreshing test DB from live DB..."
cp "$LIVE_DB" "$TEST_DB"
echo "Done: $TEST_DB is now a fresh copy."

sqlite3 "$TEST_DB" "SELECT 'lots: ' || COUNT(*) FROM lots;
SELECT 'payments: ' || COUNT(*) FROM payments;
SELECT 'assessments: ' || COUNT(*) FROM assessments;
SELECT 'deposit_batches: ' || COUNT(*) FROM deposit_batches;"

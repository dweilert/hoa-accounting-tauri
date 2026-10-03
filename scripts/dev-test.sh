#!/usr/bin/env bash
# Run the HOA app against the TEST database (hoa-test.db).
# Swaps config.json, starts the dev server, restores on exit.
# Usage: ./scripts/dev-test.sh [--reset]
#
# --reset  Refresh hoa-test.db from the live hoa.db before starting.

set -euo pipefail

TAURI_DIR="$HOME/hoa-system/tauri"
LIVE_CONFIG="$TAURI_DIR/config.json"
TEST_CONFIG="$TAURI_DIR/config.test.json"
LIVE_DB="$TAURI_DIR/hoa.db"
TEST_DB="$TAURI_DIR/hoa-test.db"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)/app"

# ── Reset flag ────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--reset" ]]; then
  echo "Resetting test DB from live DB..."
  cp "$LIVE_DB" "$TEST_DB"
  echo "Done: $TEST_DB refreshed."
fi

# Verify test config and DB exist
if [[ ! -f "$TEST_CONFIG" ]]; then
  echo "ERROR: $TEST_CONFIG not found. Create it pointing to hoa-test.db." >&2
  exit 1
fi
if [[ ! -f "$TEST_DB" ]]; then
  echo "Test DB not found. Copying from live DB..."
  cp "$LIVE_DB" "$TEST_DB"
fi

# ── Swap config ───────────────────────────────────────────────────────────────
BACKUP_CONFIG="$TAURI_DIR/config.backup.json"
cp "$LIVE_CONFIG" "$BACKUP_CONFIG"
cp "$TEST_CONFIG" "$LIVE_CONFIG"
echo "Switched to TEST database: $TEST_DB"

restore() {
  echo ""
  echo "Restoring production config..."
  cp "$BACKUP_CONFIG" "$LIVE_CONFIG"
  rm -f "$BACKUP_CONFIG"
  echo "Production config restored."
}
trap restore EXIT INT TERM

# ── Launch app ────────────────────────────────────────────────────────────────
echo "Starting dev server (Ctrl+C to stop and restore config)..."
cd "$APP_DIR"
npm run tauri dev

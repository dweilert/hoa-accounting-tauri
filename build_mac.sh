#!/usr/bin/env bash
# Build HOA Accounting as a Mac application bundle.
# Run from the repo root: ./build_mac.sh
set -euo pipefail

cd "$(dirname "$0")"

echo "=== HOA Accounting — Mac Build ==="

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "ERROR: .venv not found. Run: python3 -m venv .venv && pip install -e .[dev]"
    exit 1
fi

# Ensure PyInstaller is available
pip install --quiet pyinstaller

# Clean previous build artifacts
echo "Cleaning previous build..."
rm -rf dist/HOAAccounting build/HOAAccounting

# Build
echo "Running PyInstaller..."
pyinstaller hoa_accounting.spec --noconfirm

echo ""
echo "=== Build complete ==="
echo "Output: dist/HOAAccounting/"
echo ""
echo "To run:"
echo "  open dist/HOAAccounting/HOAAccounting"
echo ""
echo "To distribute, zip the dist/HOAAccounting/ folder:"
echo "  cd dist && zip -r HOAAccounting-mac.zip HOAAccounting/"

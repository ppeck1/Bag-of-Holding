#!/usr/bin/env bash
# Bag of Holding v2 — macOS / Linux Launcher
# Make executable: chmod +x launcher.sh
# Run: ./launcher.sh

set -e

echo ""
echo " =========================================="
echo "  Bag of Holding v2 — Local Knowledge Workbench"
echo " =========================================="
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found."
    echo "Install Python 3.11+ via https://python.org or your package manager."
    exit 1
fi

PYTHON=$(command -v python3)
echo " Python: $($PYTHON --version)"

# cd to project root (directory containing this script)
cd "$(dirname "$0")"

# Check uvicorn
if ! $PYTHON -c "import uvicorn" &> /dev/null; then
    echo " Installing dependencies..."
    $PYTHON -m pip install -r requirements.txt
fi

# Run launcher
exec $PYTHON launcher.py "$@"

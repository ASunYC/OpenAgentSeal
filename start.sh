#!/bin/bash
# Open Agent Launcher for Linux/macOS
# This script checks Python and runs the application with auto-dependency management

echo "=================================================="
echo "Open Agent Launcher"
echo "=================================================="
echo

# Check Python
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        echo "[ERROR] Python not found!"
        echo "Please install Python 3.9+ from https://www.python.org/downloads/"
        echo "Or use your package manager:"
        echo "  Ubuntu/Debian: sudo apt install python3 python3-pip"
        echo "  macOS (Homebrew): brew install python3"
        echo "  Fedora: sudo dnf install python3 python3-pip"
        exit 1
    fi
    PYTHON_CMD="python"
else
    PYTHON_CMD="python3"
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Run the Python launcher
$PYTHON_CMD run.py "$@"
exit_code=$?

if [ $exit_code -ne 0 ]; then
    echo
    echo "[ERROR] Failed to start Open Agent"
    exit $exit_code
fi
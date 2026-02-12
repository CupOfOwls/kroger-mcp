#!/bin/bash
# Kroger Discount Scanner Wrapper

PROJECT_DIR="/Users/jeremyparker/Desktop/Claude Coding Projects/kroger-mcp"

# Activate virtual environment
source "$PROJECT_DIR/.venv/bin/activate"

# Run scanner with unbuffered output
cd "$PROJECT_DIR"
python3 -u scripts/background_scanner.py

# Exit with scanner's exit code
exit $?

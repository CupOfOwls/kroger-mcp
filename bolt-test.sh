#!/bin/bash
# Test script to diagnose Bolt.ai execution issues

LOG="/Users/jeremyparker/Desktop/Claude Coding Projects/kroger-mcp/bolt-test.log"

echo "=== Test started at $(date) ===" >> "$LOG"
echo "PWD: $PWD" >> "$LOG"
echo "USER: $USER" >> "$LOG"
echo "PATH: $PATH" >> "$LOG"
echo "Environment:" >> "$LOG"
env >> "$LOG"
echo "" >> "$LOG"

# Try to run the server
echo "Attempting to start kroger-mcp..." >> "$LOG"
exec "/Users/jeremyparker/Desktop/Claude Coding Projects/kroger-mcp/.venv/bin/python3" -m kroger_mcp.server 2>&1 | tee -a "$LOG"

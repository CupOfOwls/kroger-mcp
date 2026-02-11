#!/bin/bash
# Diagnostic wrapper for Bolt.ai - logs everything and runs the server

LOG="/Users/jeremyparker/Desktop/Claude Coding Projects/kroger-mcp/bolt-diagnostic.log"
date >> "$LOG"
echo "=== BOLT.AI DIAGNOSTIC START ===" >> "$LOG"
echo "PWD: $PWD" >> "$LOG"
echo "USER: $USER" >> "$LOG"
echo "HOME: $HOME" >> "$LOG"
echo "PATH: $PATH" >> "$LOG"
echo "KROGER_CLIENT_ID: ${KROGER_CLIENT_ID:0:10}..." >> "$LOG"
echo "" >> "$LOG"
echo "Testing uv command..." >> "$LOG"
/opt/homebrew/bin/uv --version >> "$LOG" 2>&1
echo "" >> "$LOG"
echo "Running server..." >> "$LOG"

# Run the actual server and capture output
exec /opt/homebrew/bin/uv --directory "/Users/jeremyparker/Desktop/Claude Coding Projects/kroger-mcp" run kroger-mcp 2>&1 | tee -a "$LOG"

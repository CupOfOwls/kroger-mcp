#!/bin/bash
# Simple wrapper for Bolt.ai
# Changes to project directory and runs server with uv

cd "/Users/jeremyparker/Desktop/Claude Coding Projects/kroger-mcp" || exit 1
exec /opt/homebrew/bin/uv run kroger-mcp

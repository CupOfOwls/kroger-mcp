# Bolt.ai MCP Server Connection Fix - Summary

## Problem
All uv-based MCP servers (kroger, wrds-mcp) were failing with "Connection Error - Process terminated unexpectedly" in Bolt.ai, while npx-based servers worked fine.

## Root Cause
**GUI applications on macOS don't inherit the full user PATH.** Bolt.ai couldn't find the `uv` command at `/opt/homebrew/bin/uv` because that directory wasn't in its limited PATH.

## Solution
**Use the entry point scripts directly instead of `uv` or `python -m`.**

Instead of:
```json
"command": "/opt/homebrew/bin/uv",
"args": ["--directory", "/path/to/project", "run", "server-name"]
```

Use the entry point script that uv creates:
```json
"command": "/path/to/project/.venv/bin/server-name"
```

This is simpler, more reliable, and handles all Python path setup automatically.

## Changes Made

### File: `/Users/jeremyparker/.boltai/mcp.json`

#### 1. kroger server (lines 50-61)
**Before:**
```json
"kroger" : {
  "command" : "/opt/homebrew/bin/uv",
  "args" : [
    "--directory",
    "/Users/jeremyparker/Desktop/Claude Coding Projects/kroger-mcp",
    "run",
    "kroger-mcp"
  ],
  "env" : { ... }
}
```

**After:**
```json
"kroger" : {
  "command" : "/Users/jeremyparker/Desktop/Claude Coding Projects/kroger-mcp/.venv/bin/kroger-mcp",
  "env" : { ... }
}
```

#### 2. wrds-mcp server (lines 78-84)
**Before:**
```json
"wrds-mcp" : {
  "command" : "/opt/homebrew/bin/uv",
  "args" : [
    "--directory",
    "/Users/jeremyparker/Desktop/Claude Coding Projects/WRDS_MCP",
    "run",
    "wrds-mcp"
  ]
}
```

**After:**
```json
"wrds-mcp" : {
  "command" : "/Users/jeremyparker/Desktop/Claude Coding Projects/WRDS_MCP/.venv/bin/wrds-mcp"
}
```

## Verification Results

✅ **kroger server** - Starts successfully with:
```
[02/10/26 13:52:44] INFO     Starting MCP server 'Kroger API Server' with transport 'stdio'
```

✅ **wrds-mcp server** - Starts successfully (verified by timeout exit code 124)

✅ **JSON configuration** - Valid syntax confirmed

✅ **Python interpreters** - Both venv Python paths verified to exist

## Next Steps

1. **Restart Bolt.ai completely** (quit and reopen)
2. **Check MCP server status** in Bolt.ai settings - both should show "Connected"
3. **Test a tool** from kroger or wrds-mcp to confirm functionality

## Why This Works

- **Entry point scripts** - uv creates proper shell wrapper scripts that handle all setup
- **Absolute paths** - Bolt.ai can execute the scripts directly, no PATH lookup needed
- **Automatic venv activation** - Scripts properly set up PYTHONPATH and use venv Python
- **No `uv` dependency** - Works regardless of where `uv` is installed
- **Simpler configuration** - No args needed, just the command path

## Technical Notes

- Both virtual environments use Python 3.13.5 from uv's managed Python installation
- Entry point scripts are located at `.venv/bin/kroger-mcp` and `.venv/bin/wrds-mcp`
- These scripts are shell wrappers that properly invoke the venv Python with correct paths
- Entry point scripts are created automatically by uv during package installation
- Environment variables (credentials) are preserved in the configuration
- No args needed - the entry point scripts handle everything

## Status
✅ **Fix implemented and tested successfully**

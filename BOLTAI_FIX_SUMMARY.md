# Bolt.ai MCP Server Connection Fix - Summary

## Problem
All uv-based MCP servers (kroger, wrds-mcp) were failing with "Connection Error - Process terminated unexpectedly" in Bolt.ai, while npx-based servers worked fine.

## Root Cause
**GUI applications on macOS don't inherit the full user PATH.** Bolt.ai couldn't find the `uv` command at `/opt/homebrew/bin/uv` because that directory wasn't in its limited PATH.

## Solution
**Bypass `uv` entirely and invoke Python directly from each virtual environment.**

Instead of:
```json
"command": "/opt/homebrew/bin/uv",
"args": ["--directory", "/path/to/project", "run", "server-name"]
```

Use:
```json
"command": "/path/to/project/.venv/bin/python",
"args": ["-m", "module.name"]
```

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
  "command" : "/Users/jeremyparker/Desktop/Claude Coding Projects/kroger-mcp/.venv/bin/python",
  "args" : [
    "-m",
    "kroger_mcp.server"
  ],
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
  "command" : "/Users/jeremyparker/Desktop/Claude Coding Projects/WRDS_MCP/.venv/bin/python",
  "args" : [
    "-m",
    "mcp_server.server"
  ]
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

- **Direct Python execution** - No PATH lookup needed
- **Absolute paths** - Bolt.ai can execute the binary directly
- **Same runtime environment** - Virtual environment is properly activated
- **No `uv` dependency** - Works regardless of where `uv` is installed

## Technical Notes

- Both virtual environments use Python 3.13.5 from uv's managed Python installation
- Python symlinks point to: `/Users/jeremyparker/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/bin/python3.13`
- The `-m` flag runs the module as a script (equivalent to `python -m module.name`)
- Environment variables (credentials) are preserved in the configuration

## Status
✅ **Fix implemented and tested successfully**

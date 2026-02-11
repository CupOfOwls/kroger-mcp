#!/usr/bin/env node
/**
 * Node.js wrapper for running the Kroger MCP server via uv
 * This wrapper is needed for Bolt.ai compatibility
 */

const { spawn } = require('child_process');
const path = require('path');

const PROJECT_DIR = '/Users/jeremyparker/Desktop/Claude Coding Projects/kroger-mcp';
const UV_PATH = '/opt/homebrew/bin/uv';

// Spawn the uv process
const server = spawn(UV_PATH, ['--directory', PROJECT_DIR, 'run', 'kroger-mcp'], {
  stdio: 'inherit',  // Pass through stdin/stdout/stderr
  env: process.env,  // Pass through environment variables
  cwd: PROJECT_DIR
});

// Forward signals
process.on('SIGTERM', () => server.kill('SIGTERM'));
process.on('SIGINT', () => server.kill('SIGINT'));

// Exit with same code as child process
server.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code || 0);
  }
});

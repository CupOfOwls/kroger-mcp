"""
Kroger MCP Server Package

A FastMCP server that provides access to Kroger's API for grocery shopping functionality.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("kroger-mcp")
except PackageNotFoundError:  # running from a source tree that is not installed
    __version__ = "unknown"

"""
Utility tools for the Kroger MCP server
"""

from typing import Dict, Any
from datetime import datetime
from fastmcp import Context

from ..errors import translate_errors


def register_tools(mcp):
    """Register utility tools with the FastMCP server"""
    
    @mcp.tool()
    @translate_errors
    async def get_current_datetime(ctx: Context = None) -> Dict[str, Any]:
        """
        Get the current system date and time.
        
        This tool is useful for comparing with cart checkout dates, order history,
        or any other time-sensitive operations.
        
        Returns:
            Dictionary containing current date and time information
        """
        now = datetime.now()
        
        return {
            "success": True,
            "datetime": now.isoformat(),
            "date": now.date().isoformat(),
            "time": now.time().isoformat(),
            "timestamp": int(now.timestamp()),
            "formatted": now.strftime("%A, %B %d, %Y at %I:%M:%S %p")
        }

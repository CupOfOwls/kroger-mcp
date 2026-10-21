#!/usr/bin/env python3
"""
FastMCP Server for Kroger API

This server provides MCP tools for interacting with the Kroger API, including:
- Location management (search stores, get details, set preferred location)
- Product search and details
- Cart management (add items, bulk operations, tracking)
- Chain and department information
- User profile and authentication

Environment Variables Required:
- KROGER_CLIENT_ID: Your Kroger API client ID
- KROGER_CLIENT_SECRET: Your Kroger API client secret
- KROGER_REDIRECT_URI: Redirect URI for OAuth2 flow (default: http://localhost:8000/callback)
- KROGER_USER_ZIP_CODE: Default zip code for location searches (optional)
"""

import sys
from fastmcp import FastMCP

# Import all tool modules
from .tools import location_tools
from .tools import product_tools
from .tools import cart_tools
from .tools import info_tools
from .tools import profile_tools
from .tools import utility_tools
from .tools import auth_tools

# Import prompts
from . import prompts
from .errors import ToolErrorMiddleware


def create_server() -> FastMCP:
    """Create and configure the FastMCP server instance"""
    # Initialize the FastMCP server
    mcp = FastMCP(
        name="Kroger API Server",
        instructions="""
        This MCP server provides access to Kroger's API for grocery shopping functionality.
        
        Key Features:
        - Search and manage store locations
        - Find and search products
        - Add items to shopping cart with local tracking
        - Access chain and department information
        - User profile management
        
        Common workflows:
        1. Set a preferred location with set_preferred_location
        2. Search for products with search_products
        3. Add items to cart with add_items_to_cart
        4. Use bulk_add_to_cart for multiple items at once
        5. View current cart with view_current_cart
        6. Mark order as placed with mark_order_placed
        
        Authentication Flow:
        1. Use start_authentication to get an authorization URL
        2. Open the URL in your browser and authorize the application
        3. Copy the full redirect URL from your browser
        4. Use complete_authentication with the redirect URL to finish the process
        
        Cart Tracking:
        This server maintains a local record of items added to your cart since the Kroger API
        doesn't provide cart viewing functionality. When you place an order through the Kroger
        website/app, use mark_order_placed to move the current cart to order history.
        
        Errors:
        A tool that fails returns an error result. Its text says what went wrong and the next
        step to take. Its structured content holds an "error" object with a "type" (such as
        invalid_arguments, invalid_parameter, authentication_required, not_found, or
        rate_limited), a "next_step", and for Kroger API errors the HTTP status, Kroger's error
        code and message, and a correlation id. Follow the next step instead of retrying
        the same call unchanged.
        """
    )

    # Return tool failures as error results with structured details
    mcp.add_middleware(ToolErrorMiddleware())

    # Register all tools from the modules
    location_tools.register_tools(mcp)
    product_tools.register_tools(mcp)
    cart_tools.register_tools(mcp)
    info_tools.register_tools(mcp)
    profile_tools.register_tools(mcp)
    utility_tools.register_tools(mcp)
    auth_tools.register_tools(mcp)
    
    # Register prompts
    prompts.register_prompts(mcp)
    
    return mcp


def main():
    """Main entry point for the Kroger MCP server"""
    mcp = create_server()
    mcp.run()


if __name__ == "__main__":
    main()

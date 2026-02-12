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

from fastmcp import FastMCP

# Import all tool modules
from .tools import location_tools
from .tools import product_tools
from .tools import cart_tools
from .tools import info_tools
from .tools import profile_tools
from .tools import utility_tools
from .tools import auth_tools
from .tools import prediction_tools
from .tools import recipe_tools
from .tools import reporting_tools
from .tools import favorites_tools
from .tools import meal_planner_tools
from .tools import safety_tools
from .tools import deal_tools
from .tools import whole_foods_tools
from .tools import ingredient_management_tools

# Import prompts
from . import prompts


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
        - Purchase predictions and smart shopping suggestions
        - Item categorization (routine/regular/treat)
        - Ingredient safety filtering for health-optimized shopping

        Health-Optimized Shopping:
        This server includes an evidence-based ingredient filtering system designed
        to optimize for:
        1. General Health - Avoid additives linked to chronic disease outcomes
        2. Cancer Prevention - Flag IARC-classified carcinogens and genotoxic additives
        3. Metabolic Health - Identify blood sugar spiking ingredients and insulin disruptors
        4. Microbiome Optimization - Flag emulsifiers/sweeteners with gut-barrier disruption
        5. Minimizing Ultra-Processed Foods - Detect markers of heavy industrial processing

        Use safety tools to:
        - check_product_safety / check_products_safety - Scan products for bad ingredients
        - check_cart_safety - Scan entire cart for concerns
        - get_bad_ingredients_list - View 62+ flagged ingredients with severity levels
        - configure_safety_settings - Enable/disable filtering, set block mode
        - approve_product / block_product - Manage personal safe/blocked lists

        Dynamic Ingredient Management:
        Users can now fully customize the ingredient filter beyond the default 62:
        - add_custom_ingredient - Add your own ingredients to flag
        - edit_custom_ingredient - Modify custom ingredients
        - remove_custom_ingredient - Remove custom ingredients
        - list_custom_ingredients - View all custom ingredients
        - override_system_ingredient - Change default ingredient settings
        - reset_ingredient_to_default - Restore system defaults
        - import_ingredient_list / export_ingredient_list - Share ingredient lists
        - preview_ingredient_impact - See impact before adding
        - get_ingredient_info - Get detailed ingredient information
        All changes take effect immediately (no restart needed).

        Deal Discovery & Price Tracking:
        The server automatically tracks prices during searches and provides:
        - find_deals - Search for products on sale with significant discounts
        - get_price_history - View price trends and best time to buy
        - add_to_watchlist - Track items for price drops
        - scan_watchlist_for_deals - Check tracked items for current sales
        - get_latest_deal_scan - View results from automated background scans
        - Savings summaries in cart views

        Background Scanning (Optional):
        Configure automated deal scanning via launchd (Mon/Thu 9 AM):
        - Scans watchlist items automatically
        - Sends macOS notifications when deals found
        - View results with get_latest_deal_scan

        Whole Foods Catalog:
        Track clean/natural foods using safety filter:
        - add_to_whole_foods_catalog - Add products that pass safety checks
        - get_whole_foods_catalog - View tracked whole foods
        - scan_for_whole_foods - Find qualifying products by category

        Common workflows:
        1. Set a preferred location with set_preferred_location
        2. Search for products with search_products (prices automatically tracked)
        3. Find deals with find_deals (by category or search term)
        4. Check product safety with check_product_safety before adding to cart
        5. Add items to cart with add_to_cart
        6. Use check_cart_safety to scan cart for ingredient concerns
        7. View current cart with view_current_cart (includes savings summary)
        8. Mark order as placed with mark_order_placed
        9. Get purchase predictions with get_purchase_predictions
        10. Generate smart shopping lists with get_shopping_suggestions

        Automatic Pantry Integration:
        The system seamlessly tracks inventory for all items you purchase:
        - add_to_cart() → Automatically begins tracking items in pantry
        - mark_order_placed() → Automatically restocks tracked items to 100%
        This hands-free system learns your consumption patterns and enables
        predictive reordering without manual inventory management.

        Authentication Flow:
        1. Use start_authentication to get an authorization URL
        2. Open the URL in your browser and authorize the application
        3. Copy the full redirect URL from your browser
        4. Use complete_authentication with the redirect URL to finish the process

        Cart Tracking & Predictions:
        This server maintains a local record of items added to your cart and uses
        statistical analysis to predict when items need to be repurchased.
        Items are categorized as:
        - routine: Purchased frequently (every 1-14 days) - milk, bread, eggs
        - regular: Purchased occasionally (every 15-60 days) - cleaning supplies
        - treat: Seasonal/holiday items - turkey, candy
        """
    )

    # Register all tools from the modules
    location_tools.register_tools(mcp)
    product_tools.register_tools(mcp)
    cart_tools.register_tools(mcp)
    info_tools.register_tools(mcp)
    profile_tools.register_tools(mcp)
    utility_tools.register_tools(mcp)
    auth_tools.register_tools(mcp)
    prediction_tools.register_tools(mcp)
    recipe_tools.register_tools(mcp)
    reporting_tools.register_tools(mcp)
    favorites_tools.register_tools(mcp)
    meal_planner_tools.register_tools(mcp)
    safety_tools.register_tools(mcp)
    deal_tools.register_tools(mcp)
    whole_foods_tools.register_tools(mcp)
    ingredient_management_tools.register_tools(mcp)

    # Register prompts
    prompts.register_prompts(mcp)
    
    return mcp


def main():
    """Main entry point for the Kroger MCP server"""
    mcp = create_server()
    mcp.run()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
FastMCP Server for Kroger API

This server provides 18 consolidated MCP tools for interacting with the Kroger API.
Each tool uses an action-based dispatch pattern: tool(action='...', params...)

Environment Variables Required:
- KROGER_CLIENT_ID: Your Kroger API client ID
- KROGER_CLIENT_SECRET: Your Kroger API client secret
- KROGER_REDIRECT_URI: Redirect URI for OAuth2 flow (default: http://localhost:8000/callback)
- KROGER_USER_ZIP_CODE: Default zip code for location searches (optional)
"""

import asyncio
from fastmcp import FastMCP

# Import all tool modules
from .tools import location_tools
from .tools import product_tools
from .tools import cart_tools
from .tools import info_tools
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
from .tools import shopping_list_tools
from .tools import notion_tools

# Import prompts
from .config import prompts

# Import session state manager
from .config.session_state import get_session_manager


async def _cleanup_stale_sessions():
    """Background task to cleanup stale sessions."""
    session_manager = get_session_manager()
    while True:
        await asyncio.sleep(3600)  # 1 hour
        session_manager.cleanup_stale_sessions(max_age_hours=24)


def create_server() -> FastMCP:
    """Create and configure the FastMCP server instance"""
    # TODO: Implement session cleanup using FastMCP lifecycle hooks
    # The _cleanup_stale_sessions() function is defined above but not currently
    # scheduled because asyncio.create_task() requires a running event loop.
    # Once FastMCP startup hooks are implemented, schedule it there.

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
        - safety_check(action='check_product') / safety_check(action='check_products') - Scan products for bad ingredients
        - safety_check(action='check_cart') - Scan entire cart for concerns
        - safety_check(action='get_ingredients_list') - View 62+ flagged ingredients with severity levels
        - safety_check(action='configure_settings') - Enable/disable filtering, set block mode
        - safety_products(action='approve') / safety_products(action='block') - Manage personal safe/blocked lists

        Dynamic Ingredient Management:
        Users can fully customize the ingredient filter beyond the default 62:
        - ingredients(action='add') - Add your own ingredients to flag
        - ingredients(action='edit') - Modify custom ingredients
        - ingredients(action='remove') - Remove custom ingredients
        - ingredients(action='list') - View all custom ingredients
        - ingredients(action='override_system') - Change default ingredient settings
        - ingredients(action='reset_system') - Restore system defaults
        - ingredients(action='import') / ingredients(action='export') - Share ingredient lists
        - ingredients(action='preview_impact') - See impact before adding
        - ingredients(action='get_info') - Get detailed ingredient information
        All changes take effect immediately (no restart needed).

        Deal Discovery & Price Tracking:
        The server automatically tracks prices during searches and provides:
        - deals(action='find') - Search for products on sale with significant discounts
        - deals(action='get_price_history') - View price trends and best time to buy
        - deals(action='add_to_watchlist') - Track items for price drops
        - deals(action='scan_watchlist') - Check tracked items for current sales
        - deals(action='get_latest_scan') - View results from automated background scans
        - Savings summaries in cart views

        Background Scanning (Optional):
        Configure automated deal scanning via launchd (Mon/Thu 9 AM):
        - Scans watchlist items automatically
        - Sends macOS notifications when deals found
        - View results with deals(action='get_latest_scan')

        Whole Foods Catalog:
        Track clean/natural foods using safety filter:
        - whole_foods(action='add') - Add products that pass safety checks
        - whole_foods(action='get_catalog') - View tracked whole foods
        - whole_foods(action='scan') - Find qualifying products by category

        User Servings Preference (Household Size):
        Users can set their default servings per meal (household size) via
        utility(action='set_servings', servings=N). This preference is automatically used when:
        - Creating new recipes (if servings not explicitly specified)
        - Adding recipes to shopping list (if override not specified)
        - Assigning recipes to meal plans (if servings_override not specified)
        - Displaying recipe information

        The current default can be retrieved with utility(action='get_servings').

        IMPORTANT: Always display servings information when discussing recipes,
        ingredients, and shopping lists. This helps users understand quantities
        and ensures proper scaling for their household size.

        Shopping List Workflow:
        The shopping list provides an intermediate storage layer between recipes
        and the cart. This allows users to:
        - Build a consolidated list from multiple recipes
        - Review items before committing to cart
        - Auto-scale ingredients to household servings
        - Skip items already in pantry

        Shopping list workflow:
        1. utility(action='set_servings', servings=2) - Set household size (one-time setup)
        2. pantry(action='get_attention') - REQUIRED before adding to list/cart
        3. shopping_list(action='add_recipe', recipe_id=...) - Auto-scales to household default
        4. shopping_list(action='get') - Review consolidated list
        5. shopping_list(action='add_to_cart', confirm=False) - Preview what will be added
        6. shopping_list(action='add_to_cart', confirm=True) - Add to cart and clear list

        Session Requirement for Shopping:
        Before adding items to shopping list OR cart, users MUST call
        pantry(action='get_attention') at least once in the session. This ensures
        they review:
        - Items expiring soon
        - Low inventory alerts
        - Items overdue for repurchase

        One call to pantry(action='get_attention') unlocks all shopping operations
        for the remainder of the session. The requirement resets when the
        conversation ends.

        Common workflows:
        1. Set a preferred location with locations(action='set_preferred')
        2. Set household size with utility(action='set_servings')
        3. Search for products with products(action='search') (prices automatically tracked)
        4. Find deals with deals(action='find') (by category or search term)
        5. Check product safety with safety_check(action='check_product') before adding
        6. Review pantry with pantry(action='get_attention') (REQUIRED for shopping)
        7. Add recipes to shopping list with shopping_list(action='add_recipe') (auto-scaled)
        8. Review shopping list with shopping_list(action='get')
        9. Add to cart with shopping_list(action='add_to_cart') or cart(action='add')
        10. Use safety_check(action='check_cart') to scan cart for ingredient concerns
        11. View current cart with cart(action='view') (includes savings summary)
        12. Mark order as placed with cart(action='mark_placed')
        13. Get purchase predictions with predictions(action='get_predictions')

        Automatic Pantry Integration:
        The system seamlessly tracks inventory for all items you purchase:
        - cart(action='add') → Automatically begins tracking items in pantry
        - cart(action='mark_placed') → Automatically restocks tracked items to 100%
        This hands-free system learns your consumption patterns and enables
        predictive reordering without manual inventory management.

        Authentication Flow:
        1. Use auth(action='start') to get an authorization URL
        2. Open the URL in your browser and authorize the application
        3. Copy the full redirect URL from your browser
        4. Use auth(action='complete', redirect_url=...) to finish the process

        Cart Tracking & Predictions:
        This server maintains a local record of items added to your cart and uses
        statistical analysis to predict when items need to be repurchased.
        Items are categorized as:
        - routine: Purchased frequently (every 1-14 days) - milk, bread, eggs
        - regular: Purchased occasionally (every 15-60 days) - cleaning supplies
        - treat: Seasonal/holiday items - turkey, candy

        Notion Recipe Sync (optional):
        Mirror your recipe collection to a Notion database with two-way sync:
        - notion(action='setup') - Create Notion database and sync all existing recipes
        - notion(action='sync_all') - Re-push all recipes to Notion
        - notion(action='pull_changes') - Import edits made directly in Notion
        - notion(action='update_tags', recipe_id=..., tags=[...]) - Update tags on one recipe
        - notion(action='bulk_tag', tag='Favorite') - Add a tag to all synced recipes
        - notion(action='get_status') - Show sync health and stats
        - notion(action='view_recipe', recipe_id=...) - Get Notion URL for a recipe

        Notion Setup:
        1. Add NOTION_API_KEY and NOTION_WORKSPACE_ID to your .env file
        2. Call notion(action='setup') to create the database
        3. All future recipe saves/updates/deletes auto-sync to Notion
        """
    )

    # Register all tools from the modules
    location_tools.register_tools(mcp)
    product_tools.register_tools(mcp)
    cart_tools.register_tools(mcp)
    info_tools.register_tools(mcp)
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
    shopping_list_tools.register_tools(mcp)
    notion_tools.register_tools(mcp)

    # Register prompts
    prompts.register_prompts(mcp)

    return mcp


def main():
    """Main entry point for the Kroger MCP server"""
    mcp = create_server()
    mcp.run()


if __name__ == "__main__":
    main()

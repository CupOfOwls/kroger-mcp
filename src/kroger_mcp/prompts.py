"""
MCP prompts for the Kroger MCP server
"""

from typing import Optional
from fastmcp import Context


def register_prompts(mcp):
    """Register prompts with the FastMCP server"""
    
    @mcp.prompt()
    async def grocery_list_store_path(grocery_list: str, ctx: Context = None) -> str:
        """
        Generate a prompt asking for the optimal path through a store based on a grocery list.
        
        Args:
            grocery_list: A list of grocery items the user wants to purchase
            
        Returns:
            A prompt asking for the optimal shopping path
        """
        return f"""I'm planning to go grocery shopping at Kroger with this list:

{grocery_list}

Can you help me find the most efficient path through the store? Please search for these products to determine their aisle locations, then arrange them in a logical shopping order. 

If you can't find exact matches for items, please suggest similar products that are available.

IMPORTANT: Please only organize my shopping path - DO NOT add any items to my cart.
"""

    @mcp.prompt()
    async def pharmacy_open_check(ctx: Context = None) -> str:
        """
        Generate a prompt asking whether a pharmacy at the preferred Kroger location is open.
        
        Returns:
            A prompt asking about pharmacy status
        """
        return """Can you tell me if the pharmacy at my preferred Kroger store is currently open? 

Please check the department information for the pharmacy department and let me know:
1. If there is a pharmacy at my preferred store
2. If it's currently open 
3. What the hours are for today
4. What services are available at this pharmacy

Please use the get_location_details tool to find this information for my preferred location.
"""

    @mcp.prompt()
    async def set_preferred_store(zip_code: Optional[str] = None, ctx: Context = None) -> str:
        """
        Generate a prompt to help the user set their preferred Kroger store.
        
        Args:
            zip_code: Optional zip code to search near
            
        Returns:
            A prompt asking for help setting a preferred store
        """
        zip_phrase = f" near zip code {zip_code}" if zip_code else ""
        
        return f"""I'd like to set my preferred Kroger store{zip_phrase}. Can you help me with this process?

Please:
1. Search for nearby Kroger stores{zip_phrase}
2. Show me a list of the closest options with their addresses
3. Let me choose one from the list
4. Set that as my preferred location 

For each store, please show the full address, distance, and any special features or departments.
"""

    @mcp.prompt()
    async def add_recipe_to_cart(recipe_type: str = "classic apple pie", ctx: Context = None) -> str:
        """
        Generate a prompt to find a specific  recipe and add ingredients to cart. (default: classic apple pie)
        
        Args:
            recipe_type: The type of recipe to search for (e.g., "chicken curry", "vegetarian lasagna")
            
        Returns:
            A prompt asking for a recipe and to add ingredients to cart
        """
        return f"""I'd like to make a recipe: {recipe_type}. Can you help me with the following:

1. Search the web for a good {recipe_type} recipe
2. Present the recipe with ingredients and instructions
3. Look up each ingredient in my local Kroger store
4. Add all the ingredients I'll need to my cart using bulk_add_to_cart
5. If any ingredients aren't available, suggest alternatives

Before adding items to cart, please ask me if I prefer pickup or delivery for these items.
"""

    @mcp.prompt()
    async def smart_shopping_list(
        days_ahead: int = 7,
        include_seasonal: bool = True,
        ctx: Context = None
    ) -> str:
        """
        Generate a smart shopping list based on purchase history and predictions.

        Uses purchase patterns to predict what items you'll need soon and
        identifies upcoming seasonal/holiday items.

        Args:
            days_ahead: Number of days to look ahead for predictions
            include_seasonal: Whether to include upcoming holiday items

        Returns:
            A prompt for generating an intelligent shopping list
        """
        seasonal_text = (
            "Also check for any upcoming seasonal or holiday items I typically buy."
            if include_seasonal else ""
        )

        return f"""Based on my purchase history and consumption patterns, please help me
create a smart shopping list for the next {days_ahead} days.

Please:
1. Use get_purchase_predictions to find items I'll likely need to repurchase
2. Show items by urgency level (critical, high, medium, low)
3. Include routine items (daily/weekly essentials) that are due
4. Highlight any items that are overdue for repurchase
{f"5. {seasonal_text}" if seasonal_text else ""}

For each item, show:
- Product description
- Days until needed (or days overdue)
- Urgency level
- Confidence in the prediction

After showing the list, ask if I'd like to add any of these items to my cart.
Focus on items with high confidence predictions and don't suggest things I rarely buy.
"""

    @mcp.prompt()
    async def categorize_my_items(ctx: Context = None) -> str:
        """
        Generate a prompt to review and categorize tracked items.

        Returns:
            A prompt for reviewing item categorization
        """
        return """Please help me review and categorize my tracked grocery items.

Use get_category_summary to show me how my items are currently categorized:
- routine: Items I buy almost constantly (every 1-14 days)
- regular: Items I buy frequently/occasionally (every 15-60 days)
- treat: Seasonal or holiday-specific items

Then use get_items_by_category to list items in each category.

For any items that seem miscategorized, ask if I'd like to change their category.
For example, if something I buy weekly is marked as "treat", it should probably be "routine".

After reviewing, let me know if I should manually categorize any items differently.
"""

    @mcp.prompt()
    async def purchase_insights(ctx: Context = None) -> str:
        """
        Generate a prompt for analyzing purchase patterns and insights.

        Returns:
            A prompt for purchase pattern analysis
        """
        return """Please analyze my grocery purchase patterns and give me insights.

Use get_category_summary and get_purchase_predictions to help me understand:

1. **Purchase Frequency**: How often do I typically shop?
2. **Category Breakdown**: What percentage of my purchases are routine vs regular vs treats?
3. **Upcoming Needs**: What items will I likely need in the next 2 weeks?
4. **Seasonal Patterns**: Are there any items I only buy around certain holidays?
5. **Overdue Items**: Am I forgetting to repurchase anything important?

Present this as a brief shopping intelligence report with actionable recommendations.
"""

    @mcp.prompt()
    async def order_saved_recipe(
        recipe_name: str = "carbonara",
        ctx: Context = None
    ) -> str:
        """
        Generate a prompt to order ingredients from a saved recipe with opt-out.

        Args:
            recipe_name: Name or partial name of the saved recipe

        Returns:
            A prompt for ordering recipe ingredients with skip options
        """
        return f"""I want to make {recipe_name} from my saved recipes.

Please help me order the ingredients:

1. Use search_recipes to find my "{recipe_name}" recipe
2. Use get_recipe to show me the full ingredient list
3. Ask me which ingredients I already have at home
4. Use preview_recipe_order to show what will be ordered (skipping items I have)
5. Confirm the order details and ask if I want PICKUP or DELIVERY
6. Use order_recipe_ingredients with skip_items for items I already have

For each ingredient, show:
- Name and quantity needed
- Whether it has a linked Kroger product
- Estimated price if available

If any ingredients aren't linked to products yet, search for them and offer to
link them using link_ingredient_to_product for future orders.
"""

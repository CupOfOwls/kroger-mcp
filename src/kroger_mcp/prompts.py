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

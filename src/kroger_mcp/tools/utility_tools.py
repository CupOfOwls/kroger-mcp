"""
Utility tools for the Kroger MCP server
"""

from typing import Dict, Any
from datetime import datetime
from fastmcp import Context
from pydantic import Field


def register_tools(mcp):
    """Register utility tools with the FastMCP server"""

    @mcp.tool()
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

    @mcp.tool()
    async def get_default_servings(ctx: Context = None) -> Dict[str, Any]:
        """
        Get your default servings per meal preference.

        This is your "household size" setting that determines how many
        servings recipes should make by default. Used when creating recipes,
        adding to shopping list, and planning meals unless you specify a
        different amount.

        Returns:
            Current default servings setting and usage explanation
        """
        try:
            from .shared import get_default_servings

            servings = get_default_servings()

            return {
                "success": True,
                "default_servings": servings,
                "description": f"Recipes will default to {servings} serving(s)",
                "usage": {
                    "recipe_creation": f"New recipes default to {servings} servings",
                    "shopping_list": f"Shopping list scales to {servings} servings",
                    "meal_planning": f"Meal assignments default to {servings} servings",
                    "can_override": "You can override this per-recipe or per-meal"
                }
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get default servings: {str(e)}"
            }

    @mcp.tool()
    async def set_default_servings(
        servings: int = Field(..., ge=1, le=20, description="Number of servings (1-20)"),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Set your default servings per meal preference (household size).

        This determines how many servings recipes should make by default.
        Use this to match your household size or typical meal portions.

        Examples:
        - set_default_servings(2) - Cooking for 2 people
        - set_default_servings(4) - Family of 4
        - set_default_servings(1) - Meal prepping single portions

        This affects:
        - New recipes created without explicit servings
        - Shopping list ingredient scaling
        - Meal plan assignments without servings override

        Args:
            servings: Number of servings (1-20)

        Returns:
            Confirmation and updated setting
        """
        try:
            from .shared import set_default_servings, get_default_servings

            # Get old value for comparison
            old_servings = get_default_servings()

            # Set new value
            set_default_servings(servings)

            return {
                "success": True,
                "default_servings": servings,
                "previous_value": old_servings,
                "message": f"Default servings updated from {old_servings} to {servings}",
                "note": "This will affect new recipes and shopping list scaling. Existing recipes retain their servings."
            }
        except ValueError as e:
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to set default servings: {str(e)}"
            }

    @mcp.tool()
    async def get_user_profile(ctx: Context = None) -> Dict[str, Any]:
        """
        Get user profile information including preferences and settings.

        Returns:
            User preferences including location, servings, and configuration
        """
        try:
            from .shared import get_preferred_location_id, get_default_servings

            return {
                "success": True,
                "profile": {
                    "preferred_location_id": get_preferred_location_id(),
                    "default_servings_per_meal": get_default_servings()
                }
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get user profile: {str(e)}"
            }

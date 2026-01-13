"""
Reporting and export tools for the Kroger MCP server.

Provides MCP tools for:
- Analytics reports (spending, patterns, predictions)
- Data export for backup or external analysis
- Recipe-pantry integration
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastmcp import Context
from pydantic import Field


def register_tools(mcp):
    """Register reporting and export tools with the FastMCP server."""

    # ========== Analytics Reports ==========

    @mcp.tool()
    async def get_analytics_report(
        report_type: str = Field(
            description="Report type: 'spending', 'predictions', 'patterns', 'pantry'"
        ),
        days_back: int = Field(
            default=30, ge=1, le=365,
            description="Number of days to analyze (for spending/patterns)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Generate an analytics report.

        Available report types:
        - spending: Purchase breakdown by category, top products
        - predictions: How accurate predictions have been
        - patterns: Shopping behavior (day of week, modality)
        - pantry: Inventory status and items running low

        Args:
            report_type: Type of report to generate
            days_back: Analysis period for spending/patterns reports

        Returns:
            Report data based on type
        """
        try:
            if report_type == 'spending':
                from ..analytics.reporting import generate_spending_report
                report = generate_spending_report(days_back=days_back)
            elif report_type == 'predictions':
                from ..analytics.reporting import generate_prediction_accuracy_report
                report = generate_prediction_accuracy_report()
            elif report_type == 'patterns':
                from ..analytics.reporting import generate_patterns_report
                report = generate_patterns_report(days_back=days_back)
            elif report_type == 'pantry':
                from ..analytics.reporting import generate_pantry_report
                report = generate_pantry_report()
            else:
                return {
                    "success": False,
                    "error": f"Unknown report type: {report_type}. "
                             "Use 'spending', 'predictions', 'patterns', or 'pantry'"
                }

            return {
                "success": True,
                "report_type": report_type,
                "generated_at": datetime.now().isoformat(),
                "data": report
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to generate report: {str(e)}"
            }

    @mcp.tool()
    async def export_data(
        include_orders: bool = Field(
            default=True,
            description="Include order history and purchase events"
        ),
        include_products: bool = Field(
            default=True,
            description="Include product catalog and statistics"
        ),
        include_pantry: bool = Field(
            default=True,
            description="Include pantry inventory"
        ),
        include_recipes: bool = Field(
            default=True,
            description="Include saved recipes"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Export all analytics data for backup or external analysis.

        This exports your complete purchase history, product catalog,
        pantry inventory, and recipes as JSON data.

        Args:
            include_orders: Include order history
            include_products: Include product catalog
            include_pantry: Include pantry data
            include_recipes: Include recipes

        Returns:
            Complete data export
        """
        try:
            from ..analytics.reporting import export_all_data

            export = export_all_data(
                include_orders=include_orders,
                include_products=include_products,
                include_pantry=include_pantry,
                include_recipes=include_recipes
            )

            return {
                "success": True,
                "export": export
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to export data: {str(e)}"
            }

    # ========== Recipe-Pantry Integration ==========

    @mcp.tool()
    async def check_recipe_pantry(
        recipe_id: str = Field(
            description="Recipe ID to check ingredients for"
        ),
        scale: float = Field(
            default=1.0, ge=0.5, le=10.0,
            description="Recipe scale multiplier"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Check pantry inventory for recipe ingredients.

        Categorizes ingredients into:
        - have_enough: Sufficient inventory
        - low_but_usable: Low but might work
        - need_to_buy: Must purchase
        - unknown: Not tracked in pantry

        Args:
            recipe_id: ID of the recipe to check
            scale: Multiply recipe quantities by this factor

        Returns:
            Ingredient availability breakdown
        """
        try:
            from ..analytics.recipe_integration import check_recipe_pantry

            result = check_recipe_pantry(recipe_id, scale=scale)
            return result
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to check recipe: {str(e)}"
            }

    @mcp.tool()
    async def generate_recipe_shopping_list(
        recipe_ids: List[str] = Field(
            description="List of recipe IDs to shop for"
        ),
        skip_in_pantry: bool = Field(
            default=True,
            description="Skip items already in pantry"
        ),
        pantry_threshold: int = Field(
            default=30, ge=0, le=100,
            description="Pantry level to consider 'have enough'"
        ),
        combine_duplicates: bool = Field(
            default=True,
            description="Combine same ingredients across recipes"
        ),
        scale: float = Field(
            default=1.0, ge=0.5, le=10.0,
            description="Recipe scale multiplier"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Generate an optimized shopping list for multiple recipes.

        Considers current pantry inventory to skip items you have.
        Combines duplicate ingredients across recipes for efficiency.

        Args:
            recipe_ids: List of recipe IDs
            skip_in_pantry: Skip items already in pantry
            pantry_threshold: Min pantry level to skip (default 30%)
            combine_duplicates: Merge same ingredients
            scale: Recipe quantity multiplier

        Returns:
            Optimized shopping list with what to buy vs skip
        """
        try:
            from ..analytics.recipe_integration import generate_shopping_list

            result = generate_shopping_list(
                recipe_ids=recipe_ids,
                combine_duplicates=combine_duplicates,
                skip_in_pantry=skip_in_pantry,
                pantry_threshold=pantry_threshold,
                scale=scale
            )
            return result
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to generate shopping list: {str(e)}"
            }

    @mcp.tool()
    async def get_cookable_recipes(
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Find recipes you can make with current pantry inventory.

        Returns recipes sorted by feasibility - how many ingredients
        you already have in your pantry.

        Returns:
            List of recipes with feasibility scores
        """
        try:
            from ..analytics.recipe_integration import get_recipes_for_pantry

            result = get_recipes_for_pantry()
            return {
                "success": True,
                **result
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get cookable recipes: {str(e)}"
            }

"""
Meal planner tools for creating and managing meal plans.

Provides tools for:
- Creating and managing weekly/monthly meal plans
- Assigning recipes to specific days and meal slots
- Generating shopping lists for meal plans
- Adding meal plan ingredients to cart with confirmation workflow
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastmcp import Context
from pydantic import Field

from .shared import get_authenticated_client
from ..analytics import meal_planning


def register_tools(mcp):
    """Register meal planner tools with the FastMCP server."""

    # ========== Meal Plan CRUD Tools ==========

    @mcp.tool()
    async def create_meal_plan(
        name: str = Field(description="Plan name (e.g., 'Week of Jan 27')"),
        start_date: str = Field(description="Start date YYYY-MM-DD"),
        end_date: Optional[str] = Field(
            default=None,
            description="End date YYYY-MM-DD (defaults to start + 6 days for weekly)"
        ),
        plan_type: str = Field(
            default="weekly",
            description="Plan type: 'weekly', 'monthly', or 'custom'"
        ),
        description: Optional[str] = Field(
            default=None,
            description="Optional description"
        ),
        is_template: bool = Field(
            default=False,
            description="Save as reusable template"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Create a new meal plan for a date range.

        The plan provides a container for assigning recipes to specific days
        and meal slots (breakfast, lunch, dinner, snack).

        After creating a plan, use assign_meal to add recipes.
        """
        result = meal_planning.create_meal_plan(
            name=name,
            start_date=start_date,
            end_date=end_date,
            plan_type=plan_type,
            description=description,
            is_template=is_template
        )

        if ctx and result.get('success'):
            await ctx.info(f"Created meal plan '{name}'")

        return result

    @mcp.tool()
    async def get_meal_plans(
        include_past: bool = Field(
            default=False,
            description="Include plans with end_date before today"
        ),
        include_templates: bool = Field(
            default=False,
            description="Include template plans"
        ),
        limit: int = Field(
            default=20,
            ge=1,
            le=100,
            description="Maximum number of plans to return"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        List meal plans with summary info.

        Returns plan summaries including date ranges and meal counts.
        Use get_meal_plan with a specific ID for full details.
        """
        return meal_planning.get_meal_plans(
            include_past=include_past,
            include_templates=include_templates,
            limit=limit
        )

    @mcp.tool()
    async def get_meal_plan(
        plan_id: str = Field(description="Plan identifier"),
        include_recipe_details: bool = Field(
            default=True,
            description="Include full recipe names and servings"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get full details of a meal plan including all meal entries.

        Returns the plan with meals organized by date, showing which
        recipe is assigned to each slot.
        """
        return meal_planning.get_meal_plan(
            plan_id=plan_id,
            include_recipe_details=include_recipe_details
        )

    @mcp.tool()
    async def update_meal_plan(
        plan_id: str = Field(description="Plan identifier"),
        name: Optional[str] = Field(default=None, description="New plan name"),
        description: Optional[str] = Field(
            default=None,
            description="New description"
        ),
        start_date: Optional[str] = Field(
            default=None,
            description="New start date YYYY-MM-DD"
        ),
        end_date: Optional[str] = Field(
            default=None,
            description="New end date YYYY-MM-DD"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Update meal plan metadata.

        Only provided fields are updated. Use assign_meal/remove_meal
        to modify individual meal assignments.
        """
        return meal_planning.update_meal_plan(
            plan_id=plan_id,
            name=name,
            description=description,
            start_date=start_date,
            end_date=end_date
        )

    @mcp.tool()
    async def delete_meal_plan(
        plan_id: str = Field(description="Plan identifier"),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Delete a meal plan and all its meal entries.

        This permanently removes the plan and all recipe assignments.
        """
        result = meal_planning.delete_meal_plan(plan_id)

        if ctx and result.get('success'):
            await ctx.info("Deleted meal plan")

        return result

    @mcp.tool()
    async def copy_meal_plan(
        source_plan_id: str = Field(description="Plan to copy from"),
        new_name: str = Field(description="Name for the new plan"),
        new_start_date: str = Field(
            description="Start date for the new plan YYYY-MM-DD"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Copy a meal plan to a new date range.

        All meals are shifted to the new date range maintaining their
        relative positions. Useful for:
        - Copying a template to actual dates
        - Repeating a successful week
        """
        result = meal_planning.copy_meal_plan(
            source_plan_id=source_plan_id,
            new_name=new_name,
            new_start_date=new_start_date
        )

        if ctx and result.get('success'):
            await ctx.info(f"Copied plan with {result.get('meals_copied', 0)} meals")

        return result

    # ========== Meal Assignment Tools ==========

    @mcp.tool()
    async def assign_meal(
        plan_id: str = Field(description="Plan identifier"),
        recipe_id: str = Field(description="Recipe to assign"),
        meal_date: str = Field(description="Date YYYY-MM-DD"),
        meal_slot: str = Field(
            description="Meal slot: 'breakfast', 'lunch', 'dinner', or 'snack'"
        ),
        servings_override: Optional[int] = Field(
            default=None,
            ge=1,
            description="Override recipe default servings"
        ),
        notes: Optional[str] = Field(
            default=None,
            description="Optional notes for this meal"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Assign a recipe to a specific day and meal slot.

        Replaces any existing recipe in that slot. The date must be
        within the plan's date range.

        Valid meal_slots: breakfast, lunch, dinner, snack
        """
        result = meal_planning.assign_meal(
            plan_id=plan_id,
            recipe_id=recipe_id,
            meal_date=meal_date,
            meal_slot=meal_slot,
            servings_override=servings_override,
            notes=notes
        )

        if ctx and result.get('success'):
            await ctx.info(
                f"Assigned '{result.get('recipe_name')}' to {meal_slot}"
            )

        return result

    @mcp.tool()
    async def remove_meal(
        plan_id: str = Field(description="Plan identifier"),
        meal_date: str = Field(description="Date YYYY-MM-DD"),
        meal_slot: str = Field(
            description="Meal slot: 'breakfast', 'lunch', 'dinner', or 'snack'"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Remove a recipe from a meal slot.

        Clears the assignment for the specified date and slot.
        """
        return meal_planning.remove_meal(
            plan_id=plan_id,
            meal_date=meal_date,
            meal_slot=meal_slot
        )

    @mcp.tool()
    async def swap_meals(
        plan_id: str = Field(description="Plan identifier"),
        date1: str = Field(description="First date YYYY-MM-DD"),
        slot1: str = Field(description="First slot"),
        date2: str = Field(description="Second date YYYY-MM-DD"),
        slot2: str = Field(description="Second slot"),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Swap two meal assignments within the same plan.

        Useful for rearranging meals without having to remove and re-add.
        """
        return meal_planning.swap_meals(
            plan_id=plan_id,
            date1=date1,
            slot1=slot1,
            date2=date2,
            slot2=slot2
        )

    @mcp.tool()
    async def bulk_assign_meals(
        plan_id: str = Field(description="Plan identifier"),
        assignments: List[Dict[str, Any]] = Field(
            description="List of assignments. Each should have: "
            "recipe_id, meal_date, meal_slot, and optionally "
            "servings_override and notes"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Assign multiple meals at once.

        Useful for setting up a full week in one call or applying patterns
        (e.g., same breakfast every day).

        Example assignment:
        {"recipe_id": "abc123", "meal_date": "2026-01-27", "meal_slot": "dinner"}
        """
        result = meal_planning.bulk_assign_meals(
            plan_id=plan_id,
            assignments=assignments
        )

        if ctx and result.get('success'):
            await ctx.info(f"Assigned {result.get('assigned', 0)} meals")

        return result

    # ========== Shopping Integration Tools ==========

    @mcp.tool()
    async def preview_meal_plan_shopping(
        plan_id: Optional[str] = Field(
            default=None,
            description="Specific plan to shop for"
        ),
        start_date: Optional[str] = Field(
            default=None,
            description="Start of date range YYYY-MM-DD"
        ),
        end_date: Optional[str] = Field(
            default=None,
            description="End of date range YYYY-MM-DD"
        ),
        days_ahead: Optional[int] = Field(
            default=None,
            ge=1,
            le=90,
            description="Number of days from today to include"
        ),
        pantry_threshold: int = Field(
            default=30,
            ge=0,
            le=100,
            description="Skip items with pantry level above this percentage"
        ),
        combine_duplicates: bool = Field(
            default=True,
            description="Merge same ingredients across recipes"
        ),
        skip_items: Optional[List[str]] = Field(
            default=None,
            description="Ingredient names to skip (items you already have)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Preview shopping list for meal plan(s) - shows what would be ordered.

        Can specify meals by:
        - plan_id: All meals in a specific plan
        - start_date + end_date: All meals in date range (across plans)
        - days_ahead: Next N days from today

        Returns ingredients with action (ADD/SKIP/UNKNOWN) based on:
        - User skip list
        - Pantry levels (skips items above threshold)
        - Product linking (UNKNOWN if no product_id)

        Use this to review before calling add_meal_plan_to_cart.
        """
        return meal_planning.generate_meal_plan_shopping_list(
            plan_id=plan_id,
            start_date=start_date,
            end_date=end_date,
            days_ahead=days_ahead,
            pantry_threshold=pantry_threshold,
            combine_duplicates=combine_duplicates,
            skip_items=skip_items
        )

    @mcp.tool()
    async def add_meal_plan_to_cart(
        plan_id: Optional[str] = Field(
            default=None,
            description="Specific plan to shop for"
        ),
        start_date: Optional[str] = Field(
            default=None,
            description="Start of date range YYYY-MM-DD"
        ),
        end_date: Optional[str] = Field(
            default=None,
            description="End of date range YYYY-MM-DD"
        ),
        days_ahead: Optional[int] = Field(
            default=None,
            ge=1,
            le=90,
            description="Number of days from today to include"
        ),
        pantry_threshold: int = Field(
            default=30,
            ge=0,
            le=100,
            description="Skip items with pantry level above this percentage"
        ),
        skip_items: Optional[List[str]] = Field(
            default=None,
            description="Ingredient names to skip (fuzzy matching)"
        ),
        modality: str = Field(
            default="PICKUP",
            description="Fulfillment method: PICKUP or DELIVERY"
        ),
        confirm: bool = Field(
            default=False,
            description="Set to True to actually add items (after preview)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Add meal plan ingredients to cart with confirmation workflow.

        WORKFLOW (2-step process):
        Step 1: Call with confirm=False (default)
            - Returns preview with pantry status for each ingredient
            - Shows what WILL be added vs skipped
            - DOES NOT add anything to cart

        Step 2: Call with confirm=True after user approval
            - Actually adds items to cart
            - Returns order summary

        The client MUST show the Step 1 preview to the user and get
        explicit confirmation before calling Step 2.

        Can specify meals by:
        - plan_id: All meals in a specific plan
        - start_date + end_date: All meals in date range
        - days_ahead: Next N days from today
        """
        # Get shopping list
        shopping = meal_planning.generate_meal_plan_shopping_list(
            plan_id=plan_id,
            start_date=start_date,
            end_date=end_date,
            days_ahead=days_ahead,
            pantry_threshold=pantry_threshold,
            combine_duplicates=True,
            skip_items=skip_items
        )

        if not shopping.get('success'):
            return shopping

        items_to_add = shopping.get('items_to_add', [])
        items_to_skip = shopping.get('items_to_skip', [])
        items_unknown = shopping.get('items_unknown', [])

        # Preview mode - return what would be added
        if not confirm:
            return {
                "success": True,
                "confirmation_required": True,
                "preview": {
                    "date_range": shopping.get('date_range'),
                    "meals_included": shopping.get('meals_included'),
                    "recipes_included": shopping.get('recipes_included'),
                    "modality": modality,
                    "ingredients": shopping.get('ingredients', []),
                    "summary": shopping.get('summary', {})
                },
                "items_to_add": items_to_add,
                "items_to_skip": items_to_skip,
                "items_unknown": items_unknown,
                "next_step": (
                    "Review the ingredients above. "
                    "Call this tool again with confirm=True to add items to cart. "
                    "Use skip_items to exclude any additional items. "
                    "Items marked UNKNOWN need product linking via link_ingredient_to_product."
                )
            }

        # Confirm mode - actually add to cart
        if not items_to_add:
            return {
                "success": True,
                "message": (
                    "No items to add - all ingredients are well-stocked, "
                    "skipped, or need product linking"
                ),
                "items_ordered": [],
                "items_skipped": [i['name'] for i in items_to_skip],
                "items_unknown": [i['name'] for i in items_unknown]
            }

        if ctx:
            await ctx.info(f"Adding {len(items_to_add)} items to cart...")

        try:
            client = get_authenticated_client()

            # Format for Kroger API
            api_items = [
                {
                    "upc": item["product_id"],
                    "quantity": max(1, int(round(item.get("quantity", 1)))),
                    "modality": modality
                }
                for item in items_to_add
                if item.get("product_id")
            ]

            if not api_items:
                return {
                    "success": False,
                    "error": "No items with product IDs to add",
                    "items_unknown": [i['name'] for i in items_unknown]
                }

            client.cart.add_to_cart(api_items)

            # Track in local cart
            from .cart_tools import _add_item_to_local_cart
            for item in items_to_add:
                if item.get("product_id"):
                    _add_item_to_local_cart(
                        item["product_id"],
                        max(1, int(round(item.get("quantity", 1)))),
                        modality
                    )

            # Update meal plan stats
            if plan_id:
                from ..analytics.database import get_db_connection
                conn = get_db_connection()
                try:
                    conn.execute("""
                        UPDATE meal_plans
                        SET times_ordered = times_ordered + 1,
                            last_ordered_at = ?
                        WHERE id = ?
                    """, (datetime.now().isoformat(), plan_id))
                    conn.commit()
                finally:
                    conn.close()

            return {
                "success": True,
                "message": f"Added {len(api_items)} items to cart",
                "items_ordered": [
                    {
                        "name": item["name"],
                        "quantity": max(1, int(round(item.get("quantity", 1)))),
                        "product_id": item["product_id"]
                    }
                    for item in items_to_add
                    if item.get("product_id")
                ],
                "items_skipped": [i['name'] for i in items_to_skip],
                "items_unknown": [i['name'] for i in items_unknown],
                "modality": modality,
                "date_range": shopping.get('date_range'),
                "recipes_covered": [
                    r['recipe_name'] for r in shopping.get('recipes_included', [])
                ],
                "reminder": (
                    "Please review your cart in the Kroger app before checkout. "
                    "Would you like to update any pantry levels?"
                )
            }

        except Exception as cart_error:
            error_msg = str(cart_error)
            if "401" in error_msg or "Unauthorized" in error_msg:
                return {
                    "success": False,
                    "error": "Authentication failed. Run force_reauthenticate.",
                    "details": error_msg
                }
            return {
                "success": False,
                "error": f"Failed to add to cart: {error_msg}",
                "items_attempted": len(items_to_add)
            }

    # ========== Utility Tools ==========

    @mcp.tool()
    async def get_week_view(
        start_date: Optional[str] = Field(
            default=None,
            description="Monday of the week YYYY-MM-DD (defaults to current week)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get a calendar-style view of meals for a week.

        Shows each day of the week with assigned meals for all slots.
        Useful for visualizing the meal plan.
        """
        return meal_planning.get_week_view(start_date=start_date)

    @mcp.tool()
    async def get_meal_plan_summary(
        plan_id: str = Field(description="Plan identifier"),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get summary statistics for a meal plan.

        Includes:
        - Meal counts by slot (breakfast, lunch, dinner, snack)
        - Unique recipes used
        - Coverage percentage (meals filled vs available slots)
        - Pantry readiness (items needed vs available)
        """
        return meal_planning.get_meal_plan_summary(plan_id=plan_id)

"""
Meal planner tools for the Kroger MCP server.

Provides a single action-based tool for creating and managing meal plans,
assigning recipes to meal slots, and generating shopping lists.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from fastmcp import Context
from pydantic import Field

from .shared import get_authenticated_client
from ..analytics import meal_planning


def register_tools(mcp):
    """Register meal planner tools with the FastMCP server."""

    @mcp.tool()
    async def meal_plans(
        action: Literal[
            "create",
            "list",
            "get",
            "update",
            "delete",
            "copy",
            "assign_meal",
            "remove_meal",
            "swap_meals",
            "preview_shopping",
            "add_to_cart",
            "get_week_view",
            "get_summary",
            "mark_cooked",
            "check_pantry",
            "get_today",
            "get_next_meal",
            "get_upcoming",
            "get_history",
            "cleanup",
        ] = Field(
            description=(
                "Action to perform: "
                "'create' - create a new meal plan (requires name, start_date); "
                "'list' - list all meal plans; "
                "'get' - get meal plan details (requires plan_id); "
                "'update' - update plan metadata (requires plan_id); "
                "'delete' - delete a plan (requires plan_id); "
                "'copy' - copy plan to new dates (requires plan_id, new_name, new_start_date); "
                "'assign_meal' - assign recipe to meal slot (requires plan_id + recipe_id+meal_date+meal_slot or assignments); "
                "'remove_meal' - remove recipe from slot (requires plan_id, meal_date, meal_slot); "
                "'swap_meals' - swap two meal assignments (requires plan_id, date1, slot1, date2, slot2); "
                "'preview_shopping' - preview shopping list for plan(s); "
                "'add_to_cart' - add plan ingredients to cart (confirm=True to execute); "
                "'get_week_view' - calendar view of a week; "
                "'get_summary' - summary statistics (requires plan_id); "
                "'mark_cooked' - mark a meal as cooked and deduct ingredients from pantry (requires plan_id, meal_date, meal_slot); "
                "'check_pantry' - check if pantry has enough for a specific meal (requires plan_id, meal_date, meal_slot); "
                "'get_today' - show today's planned meals (breakfast/lunch/dinner/snack); "
                "'get_next_meal' - find the very next upcoming planned meal from now; "
                "'get_upcoming' - list planned meals for the next N days (optional: days, start_date); "
                "'get_history' - show past meals with cooked status (optional: days, start_date, end_date); "
                "'cleanup' - delete plans older than retention window (optional: retention_days, default 90)"
            )
        ),
        plan_id: Optional[str] = Field(
            default=None,
            description="Plan identifier. Required for: get, update, delete, copy, assign_meal, remove_meal, swap_meals, get_summary. Optional for: preview_shopping, add_to_cart"
        ),
        name: Optional[str] = Field(
            default=None,
            description="Plan name. Required for: create. Optional for: update"
        ),
        start_date: Optional[str] = Field(
            default=None,
            description="Start date YYYY-MM-DD. Required for: create. Optional for: update, preview_shopping, add_to_cart"
        ),
        end_date: Optional[str] = Field(
            default=None,
            description="End date YYYY-MM-DD. Optional for: create, update, preview_shopping, add_to_cart"
        ),
        plan_type: str = Field(
            default="weekly",
            description="Plan type: 'weekly', 'monthly', or 'custom'. Used by: create"
        ),
        description: Optional[str] = Field(
            default=None,
            description="Optional plan description. Used by: create, update"
        ),
        is_template: bool = Field(
            default=False,
            description="Save as reusable template. Used by: create"
        ),
        include_past: bool = Field(
            default=False,
            description="Include plans with end_date before today. Used by: list"
        ),
        include_templates: bool = Field(
            default=False,
            description="Include template plans. Used by: list"
        ),
        limit: int = Field(
            default=20, ge=1, le=100,
            description="Max plans to return. Used by: list"
        ),
        include_recipe_details: bool = Field(
            default=True,
            description="Include full recipe names and servings. Used by: get"
        ),
        new_name: Optional[str] = Field(
            default=None,
            description="Name for the new plan. Required for: copy"
        ),
        new_start_date: Optional[str] = Field(
            default=None,
            description="Start date for copied plan YYYY-MM-DD. Required for: copy"
        ),
        recipe_id: Optional[str] = Field(
            default=None,
            description="Recipe to assign. Required for: assign_meal (single mode)"
        ),
        meal_date: Optional[str] = Field(
            default=None,
            description="Date YYYY-MM-DD. Required for: assign_meal (single mode), remove_meal"
        ),
        meal_slot: Optional[str] = Field(
            default=None,
            description="Meal slot: 'breakfast', 'lunch', 'dinner', 'snack'. Required for: assign_meal (single mode), remove_meal"
        ),
        servings_override: Optional[int] = Field(
            default=None, ge=1,
            description="Override servings (None = use household default). Used by: assign_meal"
        ),
        notes: Optional[str] = Field(
            default=None,
            description="Optional notes. Used by: assign_meal (single mode)"
        ),
        assignments: Optional[List[Dict[str, Any]]] = Field(
            default=None,
            description=(
                "Batch assignments: [{recipe_id, meal_date, meal_slot, servings_override?, notes?}, ...] (max 100). "
                "Used by: assign_meal (batch mode)"
            )
        ),
        date1: Optional[str] = Field(
            default=None,
            description="First date YYYY-MM-DD. Required for: swap_meals"
        ),
        slot1: Optional[str] = Field(
            default=None,
            description="First meal slot. Required for: swap_meals"
        ),
        date2: Optional[str] = Field(
            default=None,
            description="Second date YYYY-MM-DD. Required for: swap_meals"
        ),
        slot2: Optional[str] = Field(
            default=None,
            description="Second meal slot. Required for: swap_meals"
        ),
        days_ahead: Optional[int] = Field(
            default=None, ge=1, le=90,
            description="Number of days from today to include. Used by: preview_shopping, add_to_cart"
        ),
        pantry_threshold: int = Field(
            default=30, ge=0, le=100,
            description="Skip items with pantry level above this %. Used by: preview_shopping, add_to_cart"
        ),
        combine_duplicates: bool = Field(
            default=True,
            description="Merge same ingredients across recipes. Used by: preview_shopping"
        ),
        skip_items: Optional[List[str]] = Field(
            default=None,
            description="Ingredient names to skip (fuzzy matching). Used by: preview_shopping, add_to_cart"
        ),
        modality: str = Field(
            default="PICKUP",
            description="Fulfillment method: PICKUP or DELIVERY. Used by: add_to_cart"
        ),
        confirm: bool = Field(
            default=False,
            description="Set to True to actually add items (after preview). Used by: add_to_cart"
        ),
        week_start_date: Optional[str] = Field(
            default=None,
            description="Monday of the week YYYY-MM-DD (defaults to current week). Used by: get_week_view"
        ),
        deduct_pantry: bool = Field(
            default=True,
            description=(
                "When marking a meal cooked, deduct ingredient quantities from pantry. "
                "Set False to mark cooked without affecting pantry. Used by: mark_cooked"
            )
        ),
        days: int = Field(
            default=7, ge=1, le=90,
            description=(
                "Number of days to look ahead or back. "
                "Used by: get_upcoming (default 7), get_history (default 30)"
            )
        ),
        retention_days: int = Field(
            default=90, ge=1, le=3650,
            description="Plans older than this many days past their end_date are pruned. Used by: cleanup"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Create and manage meal plans, assign recipes to meal slots, and shop for ingredients.

        Actions:
        - create: Create a new meal plan for a date range
        - list: List all plans with summary info
        - get: Full plan details with meals organized by date
        - update: Update plan metadata (name, description, dates)
        - delete: Permanently delete plan and all meal entries
        - copy: Copy a plan to new dates (all meals shifted proportionally)
        - assign_meal: Assign recipe(s) to meal slots, supports batch assignments
        - remove_meal: Clear a specific meal slot
        - swap_meals: Swap two meal assignments within a plan
        - preview_shopping: Preview ingredients needed for plan(s)
        - add_to_cart: Add meal plan ingredients to cart (2-step: preview then confirm=True)
        - get_week_view: Calendar view of meals for a week
        - get_summary: Statistics for a plan (coverage, recipe variety, pantry readiness)
        - mark_cooked: Mark a meal as cooked; automatically deducts ingredient quantities from pantry
        - check_pantry: Check if pantry has enough of each ingredient for a specific planned meal
        """
        match action:
            case "create":
                if not name:
                    return {"success": False, "error": "name is required for 'create'"}
                if not start_date:
                    return {"success": False, "error": "start_date is required for 'create'"}

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

            case "list":
                return meal_planning.get_meal_plans(
                    include_past=include_past,
                    include_templates=include_templates,
                    limit=limit
                )

            case "get":
                if not plan_id:
                    return {"success": False, "error": "plan_id is required for 'get'"}
                return meal_planning.get_meal_plan(
                    plan_id=plan_id,
                    include_recipe_details=include_recipe_details
                )

            case "update":
                if not plan_id:
                    return {"success": False, "error": "plan_id is required for 'update'"}
                return meal_planning.update_meal_plan(
                    plan_id=plan_id,
                    name=name,
                    description=description,
                    start_date=start_date,
                    end_date=end_date
                )

            case "delete":
                if not plan_id:
                    return {"success": False, "error": "plan_id is required for 'delete'"}
                result = meal_planning.delete_meal_plan(plan_id)
                if ctx and result.get('success'):
                    await ctx.info("Deleted meal plan")
                return result

            case "copy":
                if not plan_id:
                    return {"success": False, "error": "plan_id is required for 'copy'"}
                if not new_name:
                    return {"success": False, "error": "new_name is required for 'copy'"}
                if not new_start_date:
                    return {"success": False, "error": "new_start_date is required for 'copy'"}
                result = meal_planning.copy_meal_plan(
                    source_plan_id=plan_id,
                    new_name=new_name,
                    new_start_date=new_start_date
                )
                if ctx and result.get('success'):
                    await ctx.info(f"Copied plan with {result.get('meals_copied', 0)} meals")
                return result

            case "assign_meal":
                if not plan_id:
                    return {"success": False, "error": "plan_id is required for 'assign_meal'"}

                if assignments:
                    if len(assignments) > 100:
                        return {"success": False, "error": "Maximum 100 assignments per batch request"}
                    result = meal_planning.bulk_assign_meals(
                        plan_id=plan_id,
                        assignments=assignments
                    )
                    if ctx and result.get('success'):
                        await ctx.info(f"Assigned {result.get('assigned', 0)} meals")
                    return result

                if not all([recipe_id, meal_date, meal_slot]):
                    return {
                        "success": False,
                        "error": (
                            "For single mode, provide recipe_id, meal_date, and meal_slot. "
                            "For batch mode, provide assignments list."
                        )
                    }

                result = meal_planning.assign_meal(
                    plan_id=plan_id,
                    recipe_id=recipe_id,
                    meal_date=meal_date,
                    meal_slot=meal_slot,
                    servings_override=servings_override,
                    notes=notes
                )
                if ctx and result.get('success'):
                    await ctx.info(f"Assigned '{result.get('recipe_name')}' to {meal_slot}")
                return result

            case "remove_meal":
                if not plan_id:
                    return {"success": False, "error": "plan_id is required for 'remove_meal'"}
                if not meal_date:
                    return {"success": False, "error": "meal_date is required for 'remove_meal'"}
                if not meal_slot:
                    return {"success": False, "error": "meal_slot is required for 'remove_meal'"}
                return meal_planning.remove_meal(
                    plan_id=plan_id,
                    meal_date=meal_date,
                    meal_slot=meal_slot
                )

            case "swap_meals":
                if not plan_id:
                    return {"success": False, "error": "plan_id is required for 'swap_meals'"}
                if not all([date1, slot1, date2, slot2]):
                    return {"success": False, "error": "date1, slot1, date2, slot2 are required for 'swap_meals'"}
                return meal_planning.swap_meals(
                    plan_id=plan_id,
                    date1=date1,
                    slot1=slot1,
                    date2=date2,
                    slot2=slot2
                )

            case "preview_shopping":
                return meal_planning.generate_meal_plan_shopping_list(
                    plan_id=plan_id,
                    start_date=start_date,
                    end_date=end_date,
                    days_ahead=days_ahead,
                    pantry_threshold=pantry_threshold,
                    combine_duplicates=combine_duplicates,
                    skip_items=skip_items
                )

            case "add_to_cart":
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
                            "Items marked UNKNOWN need product linking via recipes(action='link_ingredient')."
                        )
                    }

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

                    from .cart_tools import _add_item_to_local_cart
                    for item in items_to_add:
                        if item.get("product_id"):
                            _add_item_to_local_cart(
                                item["product_id"],
                                max(1, int(round(item.get("quantity", 1)))),
                                modality
                            )

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
                            "error": "Authentication failed. Run auth(action='force_reauth').",
                            "details": error_msg
                        }
                    return {
                        "success": False,
                        "error": f"Failed to add to cart: {error_msg}",
                        "items_attempted": len(items_to_add)
                    }

            case "get_week_view":
                return meal_planning.get_week_view(start_date=week_start_date)

            case "get_summary":
                if not plan_id:
                    return {"success": False, "error": "plan_id is required for 'get_summary'"}
                return meal_planning.get_meal_plan_summary(plan_id=plan_id)

            case "mark_cooked":
                if not plan_id:
                    return {"success": False, "error": "plan_id is required for 'mark_cooked'"}
                if not meal_date:
                    return {"success": False, "error": "meal_date is required for 'mark_cooked'"}
                if not meal_slot:
                    return {"success": False, "error": "meal_slot is required for 'mark_cooked'"}

                result = meal_planning.mark_meal_cooked(
                    plan_id=plan_id,
                    meal_date=meal_date,
                    meal_slot=meal_slot,
                    deduct_pantry=deduct_pantry,
                )
                if ctx and result.get('success'):
                    summary = result.get('summary', {})
                    await ctx.info(
                        f"Marked '{result.get('recipe_name')}' as cooked. "
                        f"Deducted {summary.get('ingredients_deducted', 0)} pantry items."
                    )
                return result

            case "check_pantry":
                if not plan_id:
                    return {"success": False, "error": "plan_id is required for 'check_pantry'"}
                if not meal_date:
                    return {"success": False, "error": "meal_date is required for 'check_pantry'"}
                if not meal_slot:
                    return {"success": False, "error": "meal_slot is required for 'check_pantry'"}

                return meal_planning.check_meal_pantry_availability(
                    plan_id=plan_id,
                    meal_date=meal_date,
                    meal_slot=meal_slot,
                )

            case "get_today":
                return meal_planning.get_today_meals()

            case "get_next_meal":
                return meal_planning.get_next_meal()

            case "get_upcoming":
                return meal_planning.get_upcoming_meals(
                    days=days,
                    from_date=start_date,
                )

            case "get_history":
                return meal_planning.get_meal_history(
                    days=days,
                    start_date=start_date,
                    end_date=end_date,
                )

            case "cleanup":
                result = meal_planning.cleanup_expired_plans(retention_days=retention_days)
                if ctx and result.get("success") and result.get("plans_removed", 0) > 0:
                    await ctx.info(result["message"])
                return result

            case _:
                return {
                    "success": False,
                    "error": (
                        f"Unknown action: '{action}'. Valid actions: "
                        "create, list, get, update, delete, copy, assign_meal, remove_meal, "
                        "swap_meals, preview_shopping, add_to_cart, get_week_view, get_summary, "
                        "mark_cooked, check_pantry, get_today, get_next_meal, get_upcoming, "
                        "get_history, cleanup"
                    )
                }
